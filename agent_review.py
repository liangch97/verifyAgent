"""Agent-based field review & correction (single-track replacement of dual-track merge).

Pipeline:
  1) Rule script produces a draft dict (possibly with garbage / blanks).
  2) This module hands (rule_draft + raw_contract_text) to OpenClaw sub-agent.
  3) Sub-agent inspects every field, rewrites unreasonable ones, fills blanks,
     and returns the FINAL canonical dict + a _corrections list explaining
     every change ({field, from, to, reason}).
  4) Retries up to 2 times on timeout / non-JSON / empty response before
     giving up; on giving up returns {"_agent_error": ...} and the caller
     decides whether to push a warning and degrade to raw rule draft.

This replaces llm_field_extract.llm_extract + _merge_llm_into_rule entirely:
the agent itself is now the single source of truth.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

OPENCLAW_BIN = os.environ.get("OPENCLAW_BIN", "/root/.npm-global/bin/openclaw")
CACHE_DIR = Path(os.environ.get("AGENT_REVIEW_CACHE",
                                str(Path.home() / ".cache/contract_agent_review")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MAX_CONTRACT_CHARS = 12000
AGENT_TIMEOUT_S = 240
MAX_RETRIES = 2  # 2 retries → total 3 attempts

REVIEW_PROMPT = """你是合同字段质检员。下面给你两份输入：
(A) 合同正文全文
(B) 规则脚本的初步抽取结果(JSON)

任务（逐字段执行，不得跳过）：
1. 把 (B) 的每一项与 (A) 比对，判断是否合理。下列情况一律视为不合理：
   - 字段内容含 `[` `]` `【` `】` 等括号/方括号残留
   - `legal_rep` / `party_a.name` / `party_b.name` 含合同正文动词（如"应要求/不得/根据/按照/依据/合同/协议"）或长度<2
   - `credit_code` 不满足 18 位字母数字（GB 32100，[0-9A-HJ-NPQRTUWXY]{18}）
   - `amount` 字段无任何数字
   - 日期字段不含 4 位年份
   - 任何字段值乱码 / OCR 残留 / 控制字符
2. 不合理 → 从 (A) 找正确值改写；找不到则填 null
3. 缺失（null/空字符串） → 从 (A) 找值；找不到保持 null
4. 合理 → 原样保留

输出严格 JSON 对象（不得有 markdown、解释、代码块、前后文字）：
{
  "title": string|null,
  "contract_no": string|null,
  "contract_type": string|null,
  "project_name": string|null,
  "party_a": {"name": string|null, "credit_code": string|null, "address": string|null, "legal_rep": string|null},
  "party_b": {"name": string|null, "credit_code": string|null, "address": string|null, "legal_rep": string|null},
  "amount_yuan": number|null,
  "amount_text": string|null,
  "sign_date": string|null,
  "perform_start": string|null,
  "perform_end": string|null,
  "payment_terms": [string],
  "bank_account": {"name": string|null, "account": string|null, "bank": string|null},
  "contacts": [{"party": string, "name": string|null, "phone": string|null, "email": string|null, "address": string|null, "postcode": string|null}],
  "attachments": [string],
  "confidentiality_summary": string|null,
  "ip_clauses_summary": string|null,
  "liability_summary": string|null,
  "_corrections": [
    {"field": "party_a.legal_rep", "from": "合同[的，应要求...]", "to": "胡俊文", "reason": "原值含正文残留"},
    {"field": "contract_no", "from": null, "to": "HX-2026-0511", "reason": "原值缺失，正文第一行检出"}
  ]
}

===== (A) 合同正文 =====
<<<CONTRACT>>>

===== (B) 规则初稿 =====
<<<RULE_DRAFT>>>
"""


# ----------------------- low-level subprocess plumbing -----------------------

def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return s.strip()


def _find_final_text(obj: Any) -> str | None:
    if isinstance(obj, dict):
        v = obj.get("finalAssistantVisibleText")
        if isinstance(v, str):
            return v
        for x in obj.values():
            r = _find_final_text(x)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for x in obj:
            r = _find_final_text(x)
            if r is not None:
                return r
    return None


def _call_agent_once(prompt: str) -> tuple[str | None, str]:
    """Return (final_text, err). err empty on success."""
    try:
        proc = subprocess.run(
            [OPENCLAW_BIN, "agent", "--agent", "main", "--thinking", "off",
             "--json", "--timeout", "180", "--message", prompt],
            capture_output=True, text=True, timeout=AGENT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, f"openclaw_not_found:{OPENCLAW_BIN}"
    if proc.returncode != 0:
        return None, f"exit_{proc.returncode}:{(proc.stderr or '')[:200]}"
    try:
        envelope = json.loads(proc.stdout)
    except Exception:
        m = re.search(r"\{[\s\S]+\}\s*$", proc.stdout)
        if not m:
            return None, "envelope_not_json"
        try:
            envelope = json.loads(m.group(0))
        except Exception:
            return None, "envelope_not_json"
    final = _find_final_text(envelope)
    if final is None:
        return None, "no_final_text"
    return final, ""


def _parse_json_payload(payload: str) -> tuple[dict | None, str]:
    payload = _strip_fences(payload)
    try:
        return json.loads(payload), ""
    except Exception:
        m = re.search(r"\{[\s\S]+\}", payload)
        if not m:
            return None, "non_json_response"
        try:
            return json.loads(m.group(0)), ""
        except Exception as e:
            return None, f"json_parse_error:{e}"


# ----------------------- public entry -----------------------

def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


def review_and_correct(
    rule_draft: dict,
    raw_text: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Hand rule_draft + contract text to sub-agent; get back corrected fields.

    Returns dict shaped like the schema in REVIEW_PROMPT, plus:
        - "_corrections": list[{field,from,to,reason}]
        - "_agent_status": "ok" | "failed"
        - "_attempts": int
        - "_elapsed_s": float
        - "_cache_hit": bool
        - "_agent_error": str (only when _agent_status == "failed")
    """
    if not raw_text or not raw_text.strip():
        return {"_agent_status": "failed", "_agent_error": "empty_text", "_attempts": 0}

    text = raw_text[:MAX_CONTRACT_CHARS]
    rule_json = json.dumps(rule_draft or {}, ensure_ascii=False, sort_keys=True)
    sha = _sha(text, rule_json)
    cache_path = CACHE_DIR / f"{sha}.json"

    if cache_path.exists() and not force:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached["_cache_hit"] = True
            return cached
        except Exception:
            pass

    prompt = (REVIEW_PROMPT
              .replace("<<<CONTRACT>>>", text)
              .replace("<<<RULE_DRAFT>>>", rule_json))

    t0 = time.time()
    last_err = ""
    for attempt in range(1, MAX_RETRIES + 2):  # 1..3
        final_text, err = _call_agent_once(prompt)
        if err:
            last_err = err
            print(f"[agent_review] attempt {attempt}/{MAX_RETRIES + 1} failed: {err}", flush=True)
            continue
        data, perr = _parse_json_payload(final_text or "")
        if perr or data is None:
            last_err = perr or "empty_data"
            print(f"[agent_review] attempt {attempt} parse fail: {last_err}", flush=True)
            continue
        if not isinstance(data, dict):
            last_err = "payload_not_object"
            continue
        # success
        data["_agent_status"] = "ok"
        data["_attempts"] = attempt
        data["_elapsed_s"] = round(time.time() - t0, 1)
        data["_cache_hit"] = False
        data["_sha"] = sha
        if "_corrections" not in data or not isinstance(data["_corrections"], list):
            data["_corrections"] = []
        try:
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        except Exception:
            pass
        return data

    return {
        "_agent_status": "failed",
        "_agent_error": last_err or "unknown",
        "_attempts": MAX_RETRIES + 1,
        "_elapsed_s": round(time.time() - t0, 1),
    }


if __name__ == "__main__":
    # Self-test stub
    demo = {"party_a": {"name": "合同[的，应要求]", "legal_rep": ""}, "amount": ""}
    txt = "本合同甲方为广汽本田汽车有限公司，法定代表人胡俊文。合同金额人民币 67500 元。"
    r = review_and_correct(demo, txt)
    print(json.dumps(r, ensure_ascii=False, indent=2))
