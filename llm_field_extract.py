"""LLM-based contract field extraction via OpenClaw agent (no separate API key needed).

- Calls `openclaw agent --json --message <prompt>` as subprocess.
- Parses `finalAssistantVisibleText` from the response, then JSON-parses it.
- Caches by sha256(contract_text) to ~/.cache/contract_llm_extract/<sha>.json.
- Returns dict matching the schema below; missing/failed -> {} or partial.

Usage:
    from llm_field_extract import llm_extract
    result = llm_extract(contract_text, contract_path=Path(...))
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

OPENCLAW_BIN = os.environ.get("OPENCLAW_BIN", "/root/.npm-global/bin/openclaw")
CACHE_DIR = Path(os.environ.get("LLM_EXTRACT_CACHE", str(Path.home() / ".cache/contract_llm_extract")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Truncate raw contract to fit prompt budget (~12k chars ≈ 6k tokens of CN text)
MAX_CHARS = 12000
AGENT_TIMEOUT_S = 240  # wall budget for one call

SCHEMA_PROMPT = """你是合同字段抽取助手。请仔细阅读下方合同全文，输出**严格 JSON 对象**，不要任何解释、不要 markdown 代码块、不要前后文字。

字段同义词容错：
- 甲方 ≡ 委托方 ≡ 采购人 ≡ 发包方 ≡ Party A ≡ Buyer ≡ Client
- 乙方 ≡ 受托方 ≡ 供应商 ≡ 承包方 ≡ Party B ≡ Seller ≡ Vendor ≡ 服务方
- 信用代码 ≡ 统一社会信用代码 ≡ USCC ≡ 营业执照号
- 金额可能为中文大写（壹贰叁…元整），需转换为阿拉伯数字（人民币元）

Schema（字段缺失填 null，不要省略 key）：
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
  "confidentiality_summary": string|null,
  "ip_clauses_summary": string|null,
  "liability_summary": string|null,
  "missing_or_blank_fields": [string]
}

合同全文如下：
<<<CONTRACT>>>
"""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _cache_path(sha: str) -> Path:
    return CACHE_DIR / f"{sha}.json"


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        # remove leading ``` or ```json line
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return s.strip()


def _call_agent(prompt: str) -> Optional[str]:
    """Returns finalAssistantVisibleText or None on failure."""
    try:
        proc = subprocess.run(
            [OPENCLAW_BIN, "agent", "--agent", "main", "--thinking", "off",
             "--json", "--timeout", "180", "--message", prompt],
            capture_output=True, text=True, timeout=AGENT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    try:
        envelope = json.loads(proc.stdout)
    except Exception:
        # Sometimes wrapped, try last JSON object
        m = re.search(r"\{[\s\S]+\}\s*$", proc.stdout)
        if not m:
            return None
        try:
            envelope = json.loads(m.group(0))
        except Exception:
            return None
    # Walk to find finalAssistantVisibleText
    def _find(obj):
        if isinstance(obj, dict):
            if "finalAssistantVisibleText" in obj and isinstance(obj["finalAssistantVisibleText"], str):
                return obj["finalAssistantVisibleText"]
            for v in obj.values():
                r = _find(v)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = _find(v)
                if r is not None:
                    return r
        return None
    return _find(envelope)


def llm_extract(contract_text: str, *, force: bool = False) -> dict[str, Any]:
    """Extract contract fields via OpenClaw agent. Cached by sha256 of input.

    Returns dict; on total failure returns {"_llm_error": <msg>}.
    """
    if not contract_text or not contract_text.strip():
        return {"_llm_error": "empty_text"}
    text = contract_text[:MAX_CHARS]
    sha = _sha256_text(text)
    cp = _cache_path(sha)
    if cp.exists() and not force:
        try:
            cached = json.loads(cp.read_text(encoding="utf-8"))
            cached["_cache_hit"] = True
            return cached
        except Exception:
            pass

    prompt = SCHEMA_PROMPT.replace("<<<CONTRACT>>>", text)
    t0 = time.time()
    raw = _call_agent(prompt)
    elapsed = round(time.time() - t0, 1)
    if raw is None:
        return {"_llm_error": "agent_call_failed", "_elapsed_s": elapsed}
    payload = _strip_fences(raw)
    try:
        data = json.loads(payload)
    except Exception:
        # Try to find first {...} block
        m = re.search(r"\{[\s\S]+\}", payload)
        if not m:
            return {"_llm_error": "non_json_response", "_raw": payload[:500], "_elapsed_s": elapsed}
        try:
            data = json.loads(m.group(0))
        except Exception as e:
            return {"_llm_error": f"json_parse_error:{e}", "_raw": payload[:500], "_elapsed_s": elapsed}
    data["_elapsed_s"] = elapsed
    data["_cache_hit"] = False
    data["_sha"] = sha
    try:
        cp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return data


# ============== Dual-track diff ==============
def _norm(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return v.get("name") or "" if "name" in v else json.dumps(v, ensure_ascii=False, sort_keys=True)
    if isinstance(v, list):
        return "; ".join(_norm(x) for x in v[:5])
    return str(v)


def _eq_loose(a: Any, b: Any) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na and not nb:
        return True
    if not na or not nb:
        return False
    # normalize whitespace + drop common punctuation
    def _clean(s: str) -> str:
        return re.sub(r"[\s,，。．、（）()\"'：:]", "", s).lower()
    ca, cb = _clean(na), _clean(nb)
    if ca == cb:
        return True
    # substring tolerance for short fields
    if len(ca) >= 4 and len(cb) >= 4 and (ca in cb or cb in ca):
        return True
    return False


COMPARE_FIELDS = [
    ("title", lambda r, l: (r.get("title"), l.get("title"))),
    ("contract_no", lambda r, l: (r.get("contract_no"), l.get("contract_no"))),
    ("contract_type", lambda r, l: (r.get("contract_type"), l.get("contract_type"))),
    ("project_name", lambda r, l: (r.get("project_name"), l.get("project_name"))),
    ("party_a.name", lambda r, l: ((r.get("party_a") or {}).get("name"), (l.get("party_a") or {}).get("name"))),
    ("party_a.credit_code", lambda r, l: ((r.get("party_a") or {}).get("credit_code"), (l.get("party_a") or {}).get("credit_code"))),
    ("party_a.address", lambda r, l: ((r.get("party_a") or {}).get("address"), (l.get("party_a") or {}).get("address"))),
    ("party_a.legal_rep", lambda r, l: ((r.get("party_a") or {}).get("legal_rep"), (l.get("party_a") or {}).get("legal_rep"))),
    ("party_b.name", lambda r, l: ((r.get("party_b") or {}).get("name"), (l.get("party_b") or {}).get("name"))),
    ("party_b.credit_code", lambda r, l: ((r.get("party_b") or {}).get("credit_code"), (l.get("party_b") or {}).get("credit_code"))),
    ("party_b.address", lambda r, l: ((r.get("party_b") or {}).get("address"), (l.get("party_b") or {}).get("address"))),
    ("amount_yuan", lambda r, l: ((r.get("amount") or {}).get("value") if isinstance(r.get("amount"), dict) else r.get("amount"), l.get("amount_yuan"))),
    ("sign_date", lambda r, l: ((r.get("dates") or {}).get("sign_date") if isinstance(r.get("dates"), dict) else None, l.get("sign_date"))),
    ("bank_account.account", lambda r, l: ((r.get("bank_account") or {}).get("account"), (l.get("bank_account") or {}).get("account"))),
]


def diff_dual_track(rule_extracted: dict, llm_extracted: dict) -> list[dict]:
    """Returns list of {field, rule, llm, agree, severity} rows."""
    rows = []
    for field, getter in COMPARE_FIELDS:
        try:
            r_val, l_val = getter(rule_extracted, llm_extracted)
        except Exception:
            r_val, l_val = None, None
        agree = _eq_loose(r_val, l_val)
        # severity: if one side null and the other has value -> medium; both differ non-null -> high
        if agree:
            sev = "ok"
        elif _norm(r_val) and _norm(l_val):
            sev = "high"  # both non-empty but differ
        elif _norm(l_val) and not _norm(r_val):
            sev = "medium-llm-only"  # rule missed, llm filled
        elif _norm(r_val) and not _norm(l_val):
            sev = "medium-rule-only"
        else:
            sev = "ok"  # both empty
        rows.append({"field": field, "rule": _norm(r_val), "llm": _norm(l_val), "agree": agree, "severity": sev})
    return rows


def render_diff_md(diff_rows: list[dict], llm_meta: dict) -> str:
    lines = []
    lines.append("\n\n---\n")
    lines.append("## 双轨交叉校验（规则 vs LLM）\n")
    cache_note = "（缓存命中）" if llm_meta.get("_cache_hit") else f"（实时调用 {llm_meta.get('_elapsed_s','?')}s）"
    if llm_meta.get("_llm_error"):
        lines.append(f"> ⚠️ LLM 抽取失败：`{llm_meta.get('_llm_error')}`，本节仅展示规则结果。\n")
        return "\n".join(lines)
    lines.append(f"> LLM 抽取来源：OpenClaw agent / MiniMax {cache_note}\n")
    diffs = [r for r in diff_rows if not r["agree"]]
    agrees = [r for r in diff_rows if r["agree"]]
    lines.append(f"> 一致字段 {len(agrees)} / 比对字段 {len(diff_rows)}；差异 {len(diffs)} 项\n")
    lines.append("| 字段 | 规则结果 | LLM 结果 | 一致 | 等级 |")
    lines.append("|---|---|---|---|---|")
    for r in diff_rows:
        rule_v = (r["rule"] or "—").replace("|", "/")[:60]
        llm_v = (r["llm"] or "—").replace("|", "/")[:60]
        mark = "✓" if r["agree"] else "✗"
        lines.append(f"| {r['field']} | {rule_v} | {llm_v} | {mark} | {r['severity']} |")
    if diffs:
        lines.append("\n### 建议人工复核字段\n")
        for r in diffs:
            lines.append(f"- **{r['field']}**：规则={r['rule'] or '空'}；LLM={r['llm'] or '空'}（等级 {r['severity']}）")
    else:
        lines.append("\n双轨结果完全一致，可信度高。")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: llm_field_extract.py <contract.txt|.md>")
        sys.exit(1)
    p = Path(sys.argv[1])
    text = p.read_text(encoding="utf-8", errors="ignore")
    out = llm_extract(text)
    print(json.dumps(out, ensure_ascii=False, indent=2))
