#!/usr/bin/env python3
"""
Full QCC + Contract Review pipeline that pushes everything to Feishu IM.

Phases:
  1) Launch chrome, open QCC, click 登录
  2) Screenshot QR area, push to Feishu, poll for login (auto-refresh on QR expiry)
  3) On login: search company (Party A from contract or --company-name), extract fields, save draft
  4) Run run_contract_review.py with --company-check <draft>
  5) Push report (md + xlsx) to Feishu

Usage:
  python3 /root/full_qcc_review.py <contract_path> [--company-name <name>]
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, traceback
from pathlib import Path
import requests

# ------- Configuration loader -------
# Reads from environment variables first, then from
# $XDG_CONFIG_HOME/contract-review-feishu-bot/config.json (default ~/.config/...).
# Required keys: APP_ID, APP_SECRET, USER_OPEN_ID, OPENCLAW_PORTABLE_DIR.
def _load_config() -> dict:
    cfg_dir = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "contract-review-feishu-bot"
    cfg_file = cfg_dir / "config.json"
    data: dict = {}
    if cfg_file.is_file():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    for k in ("APP_ID", "APP_SECRET", "USER_OPEN_ID", "OPENCLAW_PORTABLE_DIR"):
        env_v = os.environ.get(k)
        if env_v:
            data[k] = env_v
    # NOTE: missing Feishu keys is no longer fatal. The openclaw-gateway is
    # the canonical IM channel; this script's direct Feishu push is optional
    # (it is only used to send the QCC QR-code interactively). When keys are
    # missing we degrade to "no Feishu push, no interactive QR" and simply
    # run the review pipeline + write outputs that openclaw will pick up.
    return data

_CFG = _load_config()
APP_ID = _CFG.get("APP_ID", "")
APP_SECRET = _CFG.get("APP_SECRET", "")
USER_OPEN_ID = _CFG.get("USER_OPEN_ID", "")
_FEISHU_ENABLED = bool(APP_ID and APP_SECRET and USER_OPEN_ID)
if not _FEISHU_ENABLED:
    print(
        "[config] Feishu APP_ID/APP_SECRET/USER_OPEN_ID not set — "
        "interactive QR-login skipped. QCC will only run if a previously "
        "saved Chrome profile already has a valid login.",
        flush=True,
    )

# ------- Paths -------
DEMO_DIR = Path(_CFG.get("OPENCLAW_PORTABLE_DIR") or "/root/contract-review-openclaw-portable")
sys.path.insert(0, str(DEMO_DIR))
sys.path.insert(0, str(DEMO_DIR / "demos"))
import qcc_login_demo as qd  # noqa: E402

PROFILE = str(DEMO_DIR / ".browser-profiles" / "qcc-demo")
QCC_HOME = "https://www.qcc.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")

OUTDIR = DEMO_DIR / "output" / "qcc_login_demo"
OUTDIR.mkdir(parents=True, exist_ok=True)
REVIEW_DIR = DEMO_DIR / "output" / "im_review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)


# ============= Feishu helpers =============
def _tat():
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=15,
    )
    return r.json()["tenant_access_token"]


def fs_text(text: str):
    if not _FEISHU_ENABLED:
        print(f"[fs_text(disabled)] {text}", flush=True)
        return
    try:
        tat = _tat()
        chunks = [text[i:i+8000] for i in range(0, len(text), 8000)] or [""]
        for i, chunk in enumerate(chunks):
            requests.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                headers={"Authorization": f"Bearer {tat}", "Content-Type": "application/json"},
                json={"receive_id": USER_OPEN_ID, "msg_type": "text",
                      "content": json.dumps({"text": chunk}, ensure_ascii=False)},
                timeout=15,
            )
    except Exception as e:
        print(f"[fs_text err] {e}", flush=True)


def fs_image(img_path: Path, caption: str = ""):
    if not _FEISHU_ENABLED:
        print(f"[fs_image(disabled)] {img_path} :: {caption}", flush=True)
        return
    try:
        tat = _tat()
        with open(img_path, "rb") as f:
            r = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {tat}"},
                files={"image": f}, data={"image_type": "message"}, timeout=60,
            )
        image_key = r.json()["data"]["image_key"]
        if caption:
            fs_text(caption)
        requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {tat}", "Content-Type": "application/json"},
            json={"receive_id": USER_OPEN_ID, "msg_type": "image",
                  "content": json.dumps({"image_key": image_key})},
            timeout=15,
        )
    except Exception as e:
        print(f"[fs_image err] {e}", flush=True)


def fs_file(fpath: Path, file_type: str = "stream"):
    if not _FEISHU_ENABLED:
        print(f"[fs_file(disabled)] {fpath}", flush=True)
        return
    try:
        tat = _tat()
        with open(fpath, "rb") as f:
            r = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/files",
                headers={"Authorization": f"Bearer {tat}"},
                files={"file": (fpath.name, f)},
                data={"file_type": file_type, "file_name": fpath.name},
                timeout=60,
            )
        file_key = r.json()["data"]["file_key"]
        requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {tat}", "Content-Type": "application/json"},
            json={"receive_id": USER_OPEN_ID, "msg_type": "file",
                  "content": json.dumps({"file_key": file_key})},
            timeout=15,
        )
    except Exception as e:
        print(f"[fs_file err] {e}", flush=True)


def md_to_pdf(md_path: Path) -> Path | None:
    """Render markdown to PDF via weasyprint with CJK font. Pure deterministic."""
    try:
        import markdown as _md
        from weasyprint import HTML, CSS
        html_body = _md.markdown(
            md_path.read_text(encoding="utf-8"),
            extensions=["tables", "fenced_code"],
        )
        css = """
        @page { size: A4; margin: 18mm 16mm; }
        html { font-family: 'Noto Sans CJK SC','Noto Sans CJK HK',sans-serif; font-size: 10.5pt; line-height: 1.55; color:#222; }
        h1 { font-size: 18pt; border-bottom: 2px solid #2563eb; padding-bottom: 4px; }
        h2 { font-size: 14pt; color:#1e3a8a; margin-top: 18px; }
        h3 { font-size: 12pt; color:#334155; }
        table { border-collapse: collapse; width: 100%; margin: 8px 0; }
        th,td { border: 1px solid #cbd5e1; padding: 5px 8px; vertical-align: top; font-size: 9.5pt; }
        th { background:#f1f5f9; }
        code { background:#f1f5f9; padding:1px 4px; border-radius:3px; font-size:9.5pt; }
        pre { background:#0f172a; color:#e2e8f0; padding:10px; border-radius:6px; font-size:9pt; white-space:pre-wrap; }
        blockquote { border-left:4px solid #94a3b8; margin:8px 0; padding:4px 12px; background:#f8fafc; color:#475569; }
        """
        html = f"<html><head><meta charset='utf-8'><title>{md_path.stem}</title></head><body>{html_body}</body></html>"
        pdf_path = md_path.with_suffix(".pdf")
        HTML(string=html).write_pdf(str(pdf_path), stylesheets=[CSS(string=css)])
        return pdf_path
    except Exception as e:
        print(f"[md_to_pdf err] {e}", flush=True)
        return None


# ============= Previous-report detection =============
_REPORT_MARKERS = (
    "合同形式化审核报告",
    "合同审核报告_行政版",
    "本报告由合同形式化审核系统自动生成",
    "审核结论",
)


def looks_like_previous_report(contract_path: Path) -> bool:
    """Return True if the file appears to be a previously generated review report.

    Avoids ingesting an admin-PDF as a fresh contract (which causes recursive
    title pollution and meaningless QCC queries).
    """
    try:
        from scripts.contract_loader import load_contract
        loaded = load_contract(contract_path)
        text = "\n".join(b.get("text", "") for b in loaded.get("ordered_blocks", []))
    except Exception:
        return False
    head = text[:3000]
    hits = sum(1 for m in _REPORT_MARKERS if m in head)
    return hits >= 2


# ============= Contract Party A extraction =============
def extract_party_a(contract_path: Path) -> str:
    """Try to extract Party A name from contract."""
    try:
        from scripts.contract_loader import load_contract
        from scripts.contract_extractor import extract_contract
        loaded = load_contract(contract_path)
        ext = extract_contract(loaded)
        pa = ext.get("party_a")
        if isinstance(pa, dict):
            return str(pa.get("name", "")).strip()
        if isinstance(pa, str):
            return pa.strip()
    except Exception as e:
        print(f"[party_a warn] {e}", flush=True)
    return ""


# ============= Display-friendly contract name =============
_MOJIBAKE_HINTS = set("åæäèçñëïüÅÆÄÈÇÑËÏÜÃÂÔÕÖÝÞßçÇÉÊËÍÎÏÓÔÕÖÚÛÜ")


def _looks_like_mojibake(name: str) -> bool:
    if not name:
        return False
    hits = sum(1 for ch in name if ch in _MOJIBAKE_HINTS)
    return hits >= 3


def _display_contract_name(contract_path: Path, party_a: str = "") -> str:
    """Return a human-readable contract name for Feishu chat display.

    When the filename is mojibake (common for Feishu IM attachments saved by
    openclaw), try to extract the title from the document content. Falls back
    to a short description with the party name and file extension.
    """
    name = contract_path.name
    if not _looks_like_mojibake(name):
        return name
    # Try extracting title from the contract
    try:
        from scripts.contract_loader import load_contract
        from scripts.contract_extractor import extract_contract
        loaded = load_contract(contract_path)
        ext = extract_contract(loaded)
        title = ext.get("title", "")
        if isinstance(title, str) and title.strip() and len(title.strip()) < 80:
            clean = title.strip()
            # Avoid polluted titles that contain party info
            if "甲方" not in clean and "乙方" not in clean:
                return clean
    except Exception:
        pass
    # Fallback: use party name + extension
    suffix = name.rsplit(".", 1)[-1] if "." in name else "docx"
    if party_a:
        return f"{party_a}合同.{suffix}"
    return f"合同文件.{suffix}"


# ============= Main pipeline =============
def _detach_to_background():
    """Fork and detach so the agent gets immediate stdout EOF.

    Child continues with stdout/stderr redirected to a per-run log file.
    """
    import os
    if os.environ.get('FULL_QCC_DETACHED') == '1':
        return
    log_dir = '/tmp/openclaw_review_logs'
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'review_%d_%d.log' % (os.getpid(), int(time.time())))
    pid = os.fork()
    if pid > 0:
        print('[scheduled] background pid=%d, log=%s' % (pid, log_path), flush=True)
        print('🚀 已开始审核，PDF 会自动推送到飞书，请稍候。', flush=True)
        os._exit(0)
    os.setsid()
    os.environ['FULL_QCC_DETACHED'] = '1'
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1); os.dup2(fd, 2); os.close(fd)
    dn = os.open('/dev/null', os.O_RDONLY); os.dup2(dn, 0); os.close(dn)




_BAD_NAME_TOKENS = (
    "应当", "违反", "提供", "支付", "承担", "应要求", "双方", "任一方",
    "本合同", "所有", "分配", "归属", "约定", "本协议", "本条", "本款",
    "如下", "下列", "上述", "前述", "委托方", "受托方", "甲方", "乙方",
    "提成", "违约金", "解除", "登记",
)


def _looks_like_bad_name(name) -> bool:
    if not isinstance(name, str):
        return True
    n = name.strip()
    if not n or len(n) < 2 or len(n) > 50:
        return True
    if any(ch in n for ch in ("】", "]", "。", "；", ";")):
        return True
    if any(tok in n for tok in _BAD_NAME_TOKENS):
        return True
    return False


def _merge_llm_into_rule(rule_ext: dict, llm_ext: dict) -> None:
    if not isinstance(llm_ext, dict) or not llm_ext or llm_ext.get("_llm_error"):
        return
    rule_pa = rule_ext.get("party_a") or {}
    llm_pa = llm_ext.get("party_a") or {}
    if isinstance(llm_pa, dict):
        if llm_pa.get("name") and (_looks_like_bad_name(rule_pa.get("name")) or not rule_pa.get("name")):
            rule_pa["name"] = llm_pa["name"]
            print("[merge] party_a.name <- LLM: " + str(llm_pa["name"]), flush=True)
        for fld in ("legal_rep", "address", "credit_code"):
            llm_v = llm_pa.get(fld)
            rule_v = rule_pa.get(fld)
            if llm_v and (not rule_v or (isinstance(rule_v, str) and (len(rule_v) > 80 or any(t in rule_v for t in _BAD_NAME_TOKENS)))):
                rule_pa[fld] = llm_v
                print("[merge] party_a." + fld + " <- LLM", flush=True)
        rule_ext["party_a"] = rule_pa
    rule_pb = rule_ext.get("party_b") or {}
    llm_pb = llm_ext.get("party_b") or {}
    if isinstance(llm_pb, dict):
        if llm_pb.get("name") and (_looks_like_bad_name(rule_pb.get("name")) or not rule_pb.get("name")):
            rule_pb["name"] = llm_pb["name"]
            print("[merge] party_b.name <- LLM: " + str(llm_pb["name"]), flush=True)
        for fld in ("legal_rep", "address", "credit_code"):
            llm_v = llm_pb.get(fld)
            rule_v = rule_pb.get(fld)
            if llm_v and (not rule_v or (isinstance(rule_v, str) and (len(rule_v) > 80 or any(t in rule_v for t in _BAD_NAME_TOKENS)))):
                rule_pb[fld] = llm_v
                print("[merge] party_b." + fld + " <- LLM", flush=True)
        rule_ext["party_b"] = rule_pb
    for fld in ("title", "contract_no", "contract_type", "project_name"):
        if not rule_ext.get(fld) and llm_ext.get(fld):
            rule_ext[fld] = llm_ext[fld]
            print("[merge] " + fld + " <- LLM", flush=True)
    if not rule_ext.get("amount") and (llm_ext.get("amount_yuan") or llm_ext.get("amount_text")):
        rule_ext["amount"] = llm_ext.get("amount_text") or str(llm_ext.get("amount_yuan"))
        print("[merge] amount <- LLM", flush=True)
    # dates
    rule_dates = rule_ext.get("dates") if isinstance(rule_ext.get("dates"), dict) else {}
    for src, dst in (("sign_date", "sign_date"), ("perform_start", "perform_start"), ("perform_end", "perform_end")):
        llm_v = llm_ext.get(src)
        if llm_v and not rule_dates.get(dst):
            rule_dates[dst] = llm_v
            print("[merge] dates." + dst + " <- LLM: " + str(llm_v), flush=True)
    if rule_dates:
        rule_ext["dates"] = rule_dates
    # bank_account
    rule_ba = rule_ext.get("bank_account") if isinstance(rule_ext.get("bank_account"), dict) else {}
    llm_ba = llm_ext.get("bank_account") or {}
    if isinstance(llm_ba, dict):
        for fld in ("name", "account", "bank"):
            if llm_ba.get(fld) and not rule_ba.get(fld):
                rule_ba[fld] = llm_ba[fld]
                print("[merge] bank_account." + fld + " <- LLM", flush=True)
        if rule_ba:
            rule_ext["bank_account"] = rule_ba
    # payment_terms
    rule_pt = rule_ext.get("payment_terms") or []
    llm_pt = llm_ext.get("payment_terms") or []
    if isinstance(llm_pt, list) and llm_pt and (not rule_pt or len(rule_pt) < len(llm_pt)):
        rule_ext["payment_terms"] = llm_pt
        print("[merge] payment_terms <- LLM (n=" + str(len(llm_pt)) + ")", flush=True)
    # summaries
    for src, dst in (("confidentiality_summary", "confidentiality_summary"),
                     ("ip_clauses_summary", "ip_clauses_summary"),
                     ("liability_summary", "liability_summary")):
        if llm_ext.get(src) and not rule_ext.get(dst):
            rule_ext[dst] = llm_ext[src]
            print("[merge] " + dst + " <- LLM", flush=True)
    # contacts
    rule_ct = rule_ext.get("contacts") or []
    llm_ct = llm_ext.get("contacts") or []
    if isinstance(llm_ct, list) and llm_ct and (not rule_ct or len(rule_ct) < len(llm_ct)):
        rule_ext["contacts"] = llm_ct
        print("[merge] contacts <- LLM (n=" + str(len(llm_ct)) + ")", flush=True)
    # attachments
    rule_at = rule_ext.get("attachments") or []
    llm_at = llm_ext.get("attachments") or []
    if isinstance(llm_at, list) and llm_at and (not rule_at or len(rule_at) < len(llm_at)):
        rule_ext["attachments"] = llm_at
        print("[merge] attachments <- LLM (n=" + str(len(llm_at)) + ")", flush=True)


def main():
    _detach_to_background()
    ap = argparse.ArgumentParser()
    ap.add_argument("contract", type=Path)
    ap.add_argument("--company-name", default="", help="Override Party A name")
    ap.add_argument("--login-timeout", type=int, default=600)
    ap.add_argument("--qr-refresh-interval", type=int, default=50,
                    help="seconds between proactive QR re-screenshots")
    args = ap.parse_args()

    contract = args.contract.resolve()
    if not contract.exists():
        fs_text(f"❌ 找不到合同文件，请确认路径是否正确。")
        sys.exit(2)

    if looks_like_previous_report(contract):
        fs_text(
            "[拒收] 检测到上传的文件是上一份《合同形式化审核报告》，"
            "而非待审合同本身。请重新上传原始合同（.docx 或合同正文 PDF）。"
        )
        sys.exit(3)

    company = args.company_name or extract_party_a(contract)
    if not company:
        fs_text("❌ 无法从合同中识别甲方名称，请在消息中注明甲方公司全称后重试。")
        sys.exit(2)

    display_name = _display_contract_name(contract, company)
    fs_text(f"📋 开始审核\n合同: {display_name}\n甲方: {company}\n步骤 1/4: 启动 QCC 登录...")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe = qd.safe_name(company)
    result_png = OUTDIR / f"qcc_result_{safe}_{stamp}.png"
    text_txt = OUTDIR / f"qcc_text_{safe}_{stamp}.txt"
    draft_json = OUTDIR / f"company_check_draft_{safe}_{stamp}.json"

    # ---- Fast path: skip QCC entirely when Feishu push is disabled ----
    # Without Feishu we cannot push the QR for the user to scan, so any
    # interactive login is impossible. Write a stub draft and proceed
    # straight to the rule-based review so the user still gets a report.
    if not _FEISHU_ENABLED:
        print("[qcc] Feishu disabled → skipping QCC, running rule-only review", flush=True)
        stub_draft = {
            "company_name": company,
            "source": "skipped_no_feishu_config",
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S+0800"),
            "fields": {"name": "", "extraction_mode": "skipped_no_feishu_config"},
            "party_a": {"name": ""},
            "extraction_mode": "skipped_no_feishu_config",
        }
        draft_json.write_text(json.dumps(stub_draft, ensure_ascii=False, indent=2), encoding="utf-8")
        _run_review_and_deliver(contract, company, draft_json, stamp)
        return

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False,
            executable_path="/usr/bin/google-chrome-stable",
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", f"--user-agent={UA}"],
            viewport={"width": 1366, "height": 900}, locale="zh-CN", user_agent=UA,
        )
        ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # ------ Try direct search first; if cookies survived, skip QR entirely ------
        def try_search() -> tuple[str, bool]:
            """Return (visible_text, blocked_by_login).
            On exception, ALWAYS try to read current page text first — rate-limit /
            CAPTCHA pages often replace the search box with a verification widget,
            causing search_company() to raise. The caller needs page text so it can
            detect 'operation too frequent' and switch to manual-verify flow instead
            of falsely concluding login expired."""
            try:
                p2 = qd.search_company(page, company)
                time.sleep(3)
                vt = qd.get_visible_text(p2)
                return vt, qd.is_qcc_login_page(vt)
            except Exception as e:
                print(f"[search err] {e}", flush=True)
                fallback_text = ""
                try:
                    fallback_text = qd.get_visible_text(page) or ""
                except Exception:
                    try:
                        fallback_text = page.evaluate("() => document.body.innerText || ''") or ""
                    except Exception:
                        fallback_text = ""
                err_msg = str(e).lower()
                if not fallback_text and ("closed" in err_msg or "target" in err_msg or "disposed" in err_msg):
                    return "", False
                return fallback_text, qd.is_qcc_login_page(fallback_text)

        fs_text("步骤 1.5/4: 复用浏览器配置文件，直接尝试搜索...")
        visible_text, blocked = try_search()
        blocked_reason = qd.detect_blocked_reason(visible_text) if visible_text else ""
        login_ok = not blocked and bool(visible_text) and not blocked_reason
        if login_ok:
            fs_text("✅ 登录态已复用，跳过扫码")
        else:
            # Unified manual-intervention branch.
            # We don't try to distinguish "login expired" vs "rate-limited" vs
            # "captcha" — they all require the human operator to look at the
            # browser window and act. We deliberately do NOT navigate away,
            # screenshot, or push images: keeping the current QCC page intact
            # is what lets the operator see exactly what QCC is asking for.
            reason_hint = ""
            if blocked_reason:
                reason_hint = f"（检测到提示：{blocked_reason[:60]}）"
            elif blocked:
                reason_hint = "（登录态失效）"
            elif not visible_text:
                reason_hint = "（页面无内容，可能被拦截）"
            fs_text(
                "⏸️ 企查查环节需要人工介入" + reason_hint + "\n"
                "  • WSL 桌面已弹出 Chrome 浏览器窗口，请在该窗口中完成相应操作\n"
                "    （扫码登录 / 点击「验证一下」/ 处理弹窗等，按页面提示来即可）\n"
                "  • 完成后无需任何操作，脚本每 8 秒自动重试，最长等待 5 分钟\n"
                "  • 若超时未完成，将自动回落为「仅规则审核」（不影响合同结论）"
            )
            wait_deadline = time.time() + min(args.login_timeout, 300)
            cleared = False
            poll_idx = 0
            last_progress_push = time.time()
            while time.time() < wait_deadline:
                time.sleep(8)
                poll_idx += 1
                visible_text, blocked = try_search()
                blocked_reason2 = qd.detect_blocked_reason(visible_text) if visible_text else ""
                if visible_text and not blocked and not blocked_reason2:
                    cleared = True
                    fs_text(f"✅ 人工介入完成（轮询 #{poll_idx}），继续抓取工商信息…")
                    break
                if time.time() - last_progress_push >= 60:
                    remaining = int(wait_deadline - time.time())
                    state = blocked_reason2 or ("登录态失效" if blocked else "未知")
                    fs_text(f"⏳ 仍在等待人工介入（剩余 {remaining}s），当前状态：{state}")
                    last_progress_push = time.time()
            if cleared:
                login_ok = True
                blocked_reason = ""
            else:
                fs_text("⏱️ 5 分钟内未检测到人工介入完成，回落为仅规则审核。")
                try:
                    ctx.close()
                except Exception:
                    pass
                stub_draft = {
                    "company_name": company,
                    "source": "skipped_qcc_manual_timeout",
                    "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S+0800"),
                    "fields": {"name": "", "extraction_mode": "skipped_qcc_manual_timeout"},
                    "party_a": {"name": ""},
                    "extraction_mode": "skipped_qcc_manual_timeout",
                }
                draft_json.write_text(json.dumps(stub_draft, ensure_ascii=False, indent=2), encoding="utf-8")
                _run_review_and_deliver(contract, company, draft_json, stamp)
                return

        # ============ Phase 2: search + extract ============
        fs_text(f"步骤 2/4: 抓取「{company}」工商信息...")
        try:
            # visible_text already populated by try_search()
            page.screenshot(path=str(result_png), full_page=True)
            text_txt.write_text(visible_text, encoding="utf-8")
            blocked_reason = qd.detect_blocked_reason(visible_text)
            if blocked_reason:
                fs_text("⚠️ 企查查页面存在访问限制提示，抓取到的信息可能不完整。")
            # Use the demo's full pipeline (build_company_check_draft) which combines:
            # - extract_company_registry_fields (legacy card parser)
            # - first_labeled_match fallbacks for company_type / business_scope / etc.
            # - extract_qcc_card_fields_v2 (new robust parser, applied via patch in build_company_check_draft)
            full_draft = qd.build_company_check_draft(company, visible_text, result_png, blocked_reason)
            party_a = full_draft.get("party_a", {}) or {}
            # Flatten to flat dict for downstream company-check loader compatibility,
            # while keeping party_a intact under "fields".
            fields = {
                "name": party_a.get("name", ""),
                "company_status": party_a.get("company_status", ""),
                "credit_code": party_a.get("credit_code", ""),
                "legal_rep": party_a.get("legal_rep", ""),
                "registered_address": party_a.get("registered_address", ""),
                "company_type": party_a.get("company_type", ""),
                "business_scope": party_a.get("business_scope", ""),
                "registered_capital": party_a.get("registered_capital", ""),
                "established_date": party_a.get("established_date", ""),
                "phone": party_a.get("phone", ""),
                "email": party_a.get("email", ""),
                "website": party_a.get("website", ""),
                "company_scale": party_a.get("company_scale", ""),
                "employee_count": party_a.get("employee_count", ""),
                "industry": party_a.get("industry", ""),
                "extraction_mode": full_draft.get("extraction_mode", "qcc_card_v2"),
            }
            draft = {
                "company_name": company, "source": "qcc",
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S+0800"),
                "fields": fields,
                # Preserve full demo draft (includes party_a / shareholders etc) for downstream loader compatibility.
                "party_a": party_a,
                "research_team": full_draft.get("research_team", []),
                "evidence_files": full_draft.get("evidence_files", []),
                "extraction_mode": full_draft.get("extraction_mode", "qcc_card_v2"),
                "result_screenshot": str(result_png),
                "visible_text_path": str(text_txt),
            }
            draft_json.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
            summary = "\n".join(f"  {k}: {v}" for k, v in fields.items() if not k.startswith("_") and k != "extraction_mode")
            fs_text(f"✅ 抓取到 {len(fields)} 字段:\n{summary}")
            fs_image(result_png, "（搜索结果截图）")
        except Exception as e:
            fs_text(f"⚠️ 企查查信息抓取失败，跳过工商核验，仅做规则审核。")
            print(f"[extract err] {e}", flush=True)
            traceback.print_exc()
            try:
                ctx.close()
            except Exception:
                pass
            stub_draft = {
                "company_name": company,
                "source": "skipped_qcc_extract_failed",
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S+0800"),
                "fields": {"name": "", "extraction_mode": "skipped_qcc_extract_failed"},
                "party_a": {"name": ""},
                "extraction_mode": "skipped_qcc_extract_failed",
            }
            draft_json.write_text(json.dumps(stub_draft, ensure_ascii=False, indent=2), encoding="utf-8")
            _run_review_and_deliver(contract, company, draft_json, stamp)
            return

        try:
            ctx.close()
        except Exception:
            pass

    _run_review_and_deliver(contract, company, draft_json, stamp)


def _run_review_and_deliver(contract: Path, company: str, draft_json: Path, stamp: str) -> None:
    """Run rule-based review using the (possibly stub) QCC draft and deliver
    the admin PDF. Shared between the QCC-enabled and QCC-skipped paths."""
    fs_text("步骤 3/4: 调用形式化审核引擎...")
    out_dir = REVIEW_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(DEMO_DIR / "run_contract_review.py"),
           str(contract), "--company-check", str(draft_json),
           "--output-dir", str(out_dir)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        tail = (res.stdout + res.stderr).splitlines()[-15:]
        print("\n".join(tail), flush=True)
    except subprocess.TimeoutExpired:
        fs_text("⚠️ 审核引擎处理超时，请稍后重试或联系技术支持。")
        sys.exit(6)

    md = next(out_dir.glob("contract_review.md"), None)
    if not md:
        fs_text("⚠️ 审核引擎未能生成报告，请重新发送合同文件重试。")
        sys.exit(7)

    md_text = md.read_text(encoding="utf-8")
    decision = ""
    confidence = ""
    for line in md_text.splitlines()[:10]:
        # Only the front-matter list lines like "- 审核结论：**xxx**".
        if not line.lstrip().startswith("-"):
            continue
        if not decision and "审核结论" in line:
            decision = line.split("：", 1)[-1].strip(" *")
        if not confidence and "置信度" in line:
            confidence = line.split("：", 1)[-1].strip(" *")
    fs_text(f"步骤 4/4: 审核完成\n结论: {decision}\n置信度: {confidence}\n正在生成行政版报告...")

    rule_ext: dict = {}
    llm_ext: dict = {}
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from llm_field_extract import llm_extract
        from admin_report import render_admin_pdf
        from scripts.contract_loader import load_contract
        from scripts.contract_extractor import extract_contract
        loaded = load_contract(contract)
        rule_ext = extract_contract(loaded)
        # Reuse template_match already produced by run_contract_review.py
        # (extract_contract itself does NOT call template_matcher).
        if not rule_ext.get("template_match"):
            try:
                _findings = sorted(out_dir.glob("contract_findings_*.json"),
                                   key=lambda x: x.stat().st_mtime, reverse=True)
                if _findings:
                    _fdata = json.loads(_findings[0].read_text(encoding="utf-8"))
                    _tm = (_fdata.get("extracted") or {}).get("template_match") or _fdata.get("template_match")
                    if _tm:
                        rule_ext["template_match"] = _tm
                        print(f"[template_match] merged from {_findings[0].name}: matched={_tm.get('matched')}", flush=True)
            except Exception as _te:
                print(f"[template_match merge warn] {_te}", flush=True)
        raw_text = "\n".join(b.get("text", "") for b in loaded.get("ordered_blocks", []))
        # LLM extraction with a shorter timeout to avoid blocking the user
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(llm_extract, raw_text)
            try:
                llm_ext = future.result(timeout=200)
            except concurrent.futures.TimeoutError:
                print("[llm] LLM extraction timed out (200s), skipping", flush=True)
                llm_ext = {}
        if llm_ext.get("_llm_error"):
            print(f"[llm warn] {llm_ext.get('_llm_error')}", flush=True)
            llm_ext = {}
        try:
            _merge_llm_into_rule(rule_ext, llm_ext)
        except Exception as _me:
            print(f"[llm merge warn] {_me}", flush=True)
    except Exception as e:
        print(f"[merge warn] {e}", flush=True)
        traceback.print_exc()

    company_check: dict = {}
    try:
        company_check = json.loads(draft_json.read_text(encoding="utf-8")) if draft_json.exists() else {}
    except Exception:
        pass

    admin_pdf = out_dir / "合同审核报告_行政版.pdf"
    try:
        render_admin_pdf(
            rule_extracted=rule_ext or {},
            llm_extracted=llm_ext or {},
            company_check=company_check,
            md_text=md_text,
            contract_path=contract,
            output_pdf=admin_pdf,
        )
    except Exception as e:
        print(f"[admin pdf err] {e}", flush=True)
        traceback.print_exc()
        fs_text(f"⚠️ 行政版 PDF 生成失败：{e}\n仅推送原始 markdown")
        fs_file(md)
        sys.exit(8)

    fs_file(admin_pdf, "pdf")
    print(f"[admin pdf] {admin_pdf}", flush=True)
    # NOTE: Do NOT send a second confirmation text here. The openclaw-gateway
    # agent will send its own "审核完成" reply after the script exits. Sending
    # fs_text here caused duplicate report messages in Feishu.
    print("🎉 审核完成，已推送行政版报告", flush=True)
    try:
        fs_text("✅ 审核完成，行政版PDF已推送。")
    except Exception as _e:
        print("[final fs_text warn] %s" % _e, flush=True)


if __name__ == "__main__":
    main()
