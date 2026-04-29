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
    missing = [k for k in ("APP_ID", "APP_SECRET", "USER_OPEN_ID") if not data.get(k)]
    if missing:
        raise SystemExit(
            f"[config] missing keys: {missing}. Set env vars or write {cfg_file}\n"
            "Example config.json:\n"
            '{\n'
            '  "APP_ID": "cli_xxxxx",\n'
            '  "APP_SECRET": "xxxxx",\n'
            '  "USER_OPEN_ID": "ou_xxxxx",\n'
            '  "OPENCLAW_PORTABLE_DIR": "/root/contract-review-openclaw-portable"\n'
            '}'
        )
    return data

_CFG = _load_config()
APP_ID = _CFG["APP_ID"]
APP_SECRET = _CFG["APP_SECRET"]
USER_OPEN_ID = _CFG["USER_OPEN_ID"]

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


# ============= Main pipeline =============
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("contract", type=Path)
    ap.add_argument("--company-name", default="", help="Override Party A name")
    ap.add_argument("--login-timeout", type=int, default=600)
    ap.add_argument("--qr-refresh-interval", type=int, default=50,
                    help="seconds between proactive QR re-screenshots")
    args = ap.parse_args()

    contract = args.contract.resolve()
    if not contract.exists():
        fs_text(f"[error] 合同文件不存在: {contract}")
        sys.exit(2)

    company = args.company_name or extract_party_a(contract)
    if not company:
        fs_text("[error] 无法从合同提取甲方名称，请用 --company-name 指定")
        sys.exit(2)

    fs_text(f"📋 开始审核\n合同: {contract.name}\n甲方: {company}\n步骤 1/4: 启动 QCC 登录...")

    from playwright.sync_api import sync_playwright

    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe = qd.safe_name(company)
    qr_png = OUTDIR / f"qcc_qr_{stamp}.png"
    result_png = OUTDIR / f"qcc_result_{safe}_{stamp}.png"
    text_txt = OUTDIR / f"qcc_text_{safe}_{stamp}.txt"
    draft_json = OUTDIR / f"company_check_draft_{safe}_{stamp}.json"

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
            """Return (visible_text, blocked_by_login)."""
            try:
                p2 = qd.search_company(page, company)
                time.sleep(3)
                vt = qd.get_visible_text(p2)
                return vt, qd.is_qcc_login_page(vt)
            except Exception as e:
                print(f"[search err] {e}", flush=True)
                return "", True

        fs_text("步骤 1.5/4: 复用浏览器配置文件，直接尝试搜索...")
        visible_text, blocked = try_search()
        login_ok = not blocked and bool(visible_text) and not qd.detect_blocked_reason(visible_text)
        if login_ok:
            fs_text("✅ 登录态已复用，跳过扫码")
        else:
            # Need QR scan
            fs_text("⚠️ 登录态失效，需要扫码")
            try:
                page.goto(QCC_HOME, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
            time.sleep(3)
            for sel in ["text=登录", "a:has-text('登录')", "button:has-text('登录')", ".login"]:
                try:
                    t = page.locator(sel).first
                    if t.count() and t.is_visible(timeout=1500):
                        t.click(timeout=3000); time.sleep(3); break
                except Exception:
                    continue
            time.sleep(2)
            try:
                page.screenshot(path=str(qr_png), full_page=True)
                fs_image(qr_png, "请扫描二维码登录企查查（约 60 秒有效，过期会自动刷新）")
            except Exception as e:
                print(f"[qr screenshot err] {e}", flush=True)

            t0 = time.time()
            last_push = time.time()
            last_qr_size = qr_png.stat().st_size if qr_png.exists() else 0
            while time.time() - t0 < args.login_timeout:
                # Re-attempt search every 10s — if it works, we're logged in
                if int(time.time() - t0) % 12 == 0:
                    visible_text, blocked = try_search()
                    if not blocked and visible_text and not qd.detect_blocked_reason(visible_text):
                        login_ok = True
                        fs_text("✅ 登录成功（搜索校验通过）")
                        break
                    # Go back to login page so user can scan again
                    try:
                        page.goto(QCC_HOME, wait_until="domcontentloaded", timeout=30000); time.sleep(2)
                        for sel in ["text=登录", "a:has-text('登录')", ".login"]:
                            try:
                                t = page.locator(sel).first
                                if t.count() and t.is_visible(timeout=1500):
                                    t.click(timeout=3000); break
                            except Exception:
                                continue
                        time.sleep(3)
                    except Exception:
                        pass

                try:
                    text = page.evaluate("() => document.body.innerText || ''")
                except Exception as e:
                    fs_text(f"[fatal] 浏览器异常: {e}"); break
                expired = any(m in text for m in ["二维码已失效", "二维码失效", "二维码已过期", "点击刷新", "刷新二维码"])
                if expired or (time.time() - last_push > 50):
                    if expired:
                        for sel in ["text=点击刷新", "text=刷新二维码", ".login-qr-refresh"]:
                            try:
                                loc = page.locator(sel).first
                                if loc.count() and loc.is_visible(timeout=1500):
                                    loc.click(timeout=2000); break
                            except Exception:
                                continue
                        time.sleep(3)
                    try:
                        page.screenshot(path=str(qr_png), full_page=True)
                        new_size = qr_png.stat().st_size
                        if abs(new_size - last_qr_size) > 500 or expired:
                            fs_image(qr_png, "🔄 二维码已刷新" if expired else "（最新二维码）")
                            last_qr_size = new_size
                        last_push = time.time()
                    except Exception:
                        pass
                time.sleep(2)
            if not login_ok:
                fs_text("⏱️ 登录超时")
                ctx.close(); sys.exit(3)
            # Re-run search after fresh login
            visible_text, blocked = try_search()
            if blocked:
                fs_text("[失败] 登录后搜索仍被拦截"); ctx.close(); sys.exit(4)

        # ============ Phase 2: search + extract ============
        fs_text(f"步骤 2/4: 抓取「{company}」工商信息...")
        try:
            # visible_text already populated by try_search()
            page.screenshot(path=str(result_png), full_page=True)
            text_txt.write_text(visible_text, encoding="utf-8")
            blocked_reason = qd.detect_blocked_reason(visible_text)
            if blocked_reason:
                fs_text(f"[警告] {blocked_reason}")
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
            fs_text(f"[err] 抓取失败: {e}")
            traceback.print_exc()
            ctx.close(); sys.exit(5)

        try:
            ctx.close()
        except Exception:
            pass

    # ============ Phase 3: contract review ============
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
        fs_text("[err] 审核超时")
        sys.exit(6)

    # ============ Phase 4: deliver ============
    md = next(out_dir.glob("contract_review.md"), None)
    xlsx = next(out_dir.glob("*.xlsx"), None)
    findings = next(out_dir.glob("contract_findings_*.json"), None)
    if not md:
        fs_text("[err] 审核未产出 md")
        sys.exit(7)

    # Parse decision
    md_text = md.read_text(encoding="utf-8")
    decision = ""
    confidence = ""
    for line in md_text.splitlines()[:10]:
        if "审核结论" in line: decision = line.split("：", 1)[-1].strip("* ")
        if "置信度" in line: confidence = line.split("：", 1)[-1].strip()
    fs_text(f"步骤 4/4: 审核完成\n结论: {decision}\n置信度: {confidence}\n正在生成行政版报告...")

    # ====== Dual-track LLM cross-check (internal only, not exposed to user) ======
    rule_ext = {}
    llm_ext = {}
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from llm_field_extract import llm_extract
        from admin_report import render_admin_pdf
        from scripts.contract_loader import load_contract
        from scripts.contract_extractor import extract_contract
        loaded = load_contract(contract)
        rule_ext = extract_contract(loaded)
        raw_text = "\n".join(b.get("text", "") for b in loaded.get("ordered_blocks", []))
        llm_ext = llm_extract(raw_text)
        if llm_ext.get("_llm_error"):
            print(f"[llm warn] {llm_ext.get('_llm_error')}", flush=True)
            llm_ext = {}
    except Exception as e:
        print(f"[merge warn] {e}", flush=True)
        traceback.print_exc()

    # ====== Generate admin-friendly PDF ======
    company_check = {}
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
    fs_text("🎉 审核完成，已推送行政版报告")


if __name__ == "__main__":
    main()
