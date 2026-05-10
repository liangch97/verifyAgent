from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover - optional demo dependency
    raise SystemExit(
        "This demo requires Playwright. Install it with:\n"
        "  pip install -r requirements-demo.txt\n"
        "If Playwright asks for a browser, prefer using the local Chrome installation."
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output" / "qcc_login_demo"
DEFAULT_PROFILE_DIR = ROOT / ".browser-profiles" / "qcc-demo"
DEFAULT_LOGIN_TIMEOUT_SECONDS = 900
DEFAULT_LOGIN_ONLY_HOLD_SECONDS = 900
QCC_HOME = "https://www.qcc.com/"
QCC_LOGIN_CANDIDATES = [
    "https://www.qcc.com/user_login",
    "https://www.qcc.com/user_login?back=/",
]

BLOCK_KEYWORDS = [
    "验证码",
    "滑块",
    "访问受限",
    "访问被阻断",
    "安全威胁",
    "访问频繁",
    "操作过于频繁",
    "验证后再操作",
    "验证一下",
    "请求异常",
    "WAF",
]
ACCESS_BLOCK_PATTERNS = [
    r"\b403\s*Forbidden\b",
    r"\bHTTP\s*403\b",
    r"错误\s*403",
    r"403\s*错误",
    r"\b405\s*Method\s*Not\s*Allowed\b",
    r"\bHTTP\s*405\b",
    r"错误\s*405",
    r"405\s*错误",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="QCC QR-login demo. It uses a normal visible browser session and does not bypass login/captcha/WAF."
    )
    parser.add_argument("company_name", help="Company name to search after QR login, for example 华为技术有限公司")
    parser.add_argument(
        "--company-url",
        default="",
        help="Optional exact QCC detail URL, for example https://www.qcc.com/firm/xxx.html. Requires QR login first.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument(
        "--reuse-profile",
        action="store_true",
        help="Reuse --profile-dir across runs so QCC cookies/local browser session can survive between runs on the same machine.",
    )
    parser.add_argument("--login-timeout", type=int, default=DEFAULT_LOGIN_TIMEOUT_SECONDS, help="Seconds to wait for QR login")
    parser.add_argument(
        "--require-login",
        action="store_true",
        help="Kept for compatibility. Company search never starts unless QR login is detected.",
    )
    parser.add_argument("--headless", action="store_true", help="Run headless. Not recommended for QR login.")
    parser.add_argument("--login-only", action="store_true", help="Only open QCC login and save the QR screenshot.")
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=DEFAULT_LOGIN_ONLY_HOLD_SECONDS,
        help="When used with --login-only, keep the visible browser open for this many seconds before closing.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.profile_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_profile_dir = args.profile_dir if args.reuse_profile else args.profile_dir / stamp
    run_profile_dir.mkdir(parents=True, exist_ok=True)
    login_screenshot = args.output_dir / f"qcc_login_qr_{stamp}.png"
    result_screenshot = args.output_dir / f"qcc_result_{safe_name(args.company_name)}_{stamp}.png"
    text_path = args.output_dir / f"qcc_visible_text_{safe_name(args.company_name)}_{stamp}.txt"
    draft_json_path = args.output_dir / f"company_check_draft_{safe_name(args.company_name)}_{stamp}.json"
    run_log_path = args.output_dir / f"qcc_login_demo_run_{stamp}.md"
    latest_log_path = args.output_dir / "qcc_login_demo_latest.md"
    latest_json_path = args.output_dir / "qcc_login_demo_latest.json"

    chrome_path = find_chrome()

    with sync_playwright() as p:
        launch_kwargs: dict[str, Any] = {
            "headless": args.headless,
            "viewport": {"width": 1366, "height": 900},
            "locale": "zh-CN",
        }
        if chrome_path:
            launch_kwargs["executable_path"] = str(chrome_path)
        # else: fall back to Playwright's bundled chromium (Linux/WSL has no Chrome channel)

        context = p.chromium.launch_persistent_context(str(run_profile_dir), **launch_kwargs)
        page = context.pages[0] if context.pages else context.new_page()

        try:
            existing_login = False
            if args.reuse_profile:
                open_qcc_home(page)
                existing_login = is_probably_logged_in(page)

            if existing_login:
                page.screenshot(path=str(login_screenshot), full_page=True)
                write_run_log(
                    log_path=run_log_path,
                    latest_log_path=latest_log_path,
                    latest_json_path=latest_json_path,
                    company_name=args.company_name,
                    login_screenshot=login_screenshot,
                    result_screenshot=None,
                    draft_json_path=None,
                    status="already_logged_in",
                    note=(
                        "Existing QCC browser session was detected from --reuse-profile. "
                        "QR scan was skipped. No company information was queried yet."
                    ),
                    blocked_reason="",
                )
                print("[login] existing QCC session detected from --reuse-profile; QR scan skipped.")
                print(f"[session-screenshot] {login_screenshot}")
                print(f"[run-log] {run_log_path}")
                print(f"[latest-log] {latest_log_path}")
                print(f"[preview-html] {latest_log_path.with_suffix('.html')}")
            else:
                open_qcc_login(page)
                page.screenshot(path=str(login_screenshot), full_page=True)
                write_run_log(
                    log_path=run_log_path,
                    latest_log_path=latest_log_path,
                    latest_json_path=latest_json_path,
                    company_name=args.company_name,
                    login_screenshot=login_screenshot,
                    result_screenshot=None,
                    draft_json_path=None,
                    status="login_qr_captured",
                    note=(
                        "Only a login QR code was captured. No company information was queried. "
                        f"In login-only mode the browser stays open for up to {args.hold_seconds} seconds; "
                        f"in verification mode it stays open until login is detected or {args.login_timeout} seconds pass."
                    ),
                    blocked_reason="",
                )
                print(f"[login-qr] {login_screenshot}")
                print(f"[run-log] {run_log_path}")
                print(f"[latest-log] {latest_log_path}")
                print(f"[preview-html] {latest_log_path.with_suffix('.html')}")
                print("Scan the QR code in the browser or from the screenshot. Do not share the screenshot publicly.")

            if args.login_only:
                hold_seconds = max(args.hold_seconds, 1)
                print(f"[hold] Keeping the browser open for {hold_seconds} seconds.")
                time.sleep(hold_seconds)
                print("[done] Login-only flow finished. No company information was queried.")
                return

            if not existing_login:
                if not wait_for_login_checkpoint(
                    page=page,
                    timeout_seconds=args.login_timeout,
                    log_path=run_log_path,
                    latest_log_path=latest_log_path,
                    latest_json_path=latest_json_path,
                    company_name=args.company_name,
                    login_screenshot=login_screenshot,
                    result_screenshot=None,
                    status_on_timeout="login_not_detected",
                    note_on_timeout=(
                        f"QR login was not detected within {args.login_timeout} seconds. "
                        "No company information was queried."
                    ),
                ):
                    return

            login_redirect_retries = 0
            max_login_redirect_retries = 2
            while True:
                if args.company_url:
                    page = open_company_detail_url(page, args.company_url)
                else:
                    page = search_company(page, args.company_name)
                __import__("time").sleep(3.0)

                visible_text = get_visible_text(page)
                page.screenshot(path=str(result_screenshot), full_page=True)
                text_path.write_text(visible_text, encoding="utf-8")

                blocked_reason = detect_blocked_reason(visible_text)
                if not is_qcc_login_page(visible_text):
                    break
                if login_redirect_retries >= max_login_redirect_retries:
                    write_run_log(
                        log_path=run_log_path,
                        latest_log_path=latest_log_path,
                        latest_json_path=latest_json_path,
                        company_name=args.company_name,
                        login_screenshot=login_screenshot,
                        result_screenshot=result_screenshot,
                        draft_json_path=None,
                        status="login_required_after_retry_limit",
                        note=(
                            "QCC redirected to the login page again after repeated login waits. "
                            f"The browser will stay open for another {args.login_timeout} seconds for manual inspection, "
                            "then stop without generating a company_check draft."
                        ),
                        blocked_reason="",
                    )
                    print("[login-required] QCC redirected to the login page again after repeated login waits.")
                    print(f"[hold] Keeping the browser open for {args.login_timeout} seconds before stopping.")
                    print("[qcc] No company verification data was obtained; do not report QCC verification as successful.")
                    print(f"[result-screenshot] {result_screenshot}")
                    print(f"[visible-text] {text_path}")
                    print(f"[latest-log] {latest_log_path}")
                    print(f"[preview-html] {latest_log_path.with_suffix('.html')}")
                    page.wait_for_timeout(max(args.login_timeout, 1) * 1000)
                    return

                write_run_log(
                    log_path=run_log_path,
                    latest_log_path=latest_log_path,
                    latest_json_path=latest_json_path,
                    company_name=args.company_name,
                    login_screenshot=login_screenshot,
                    result_screenshot=result_screenshot,
                    draft_json_path=None,
                    status="login_required_after_search",
                    note=(
                        "QCC redirected to the login page during company lookup. "
                        f"The browser will stay open and wait up to {args.login_timeout} seconds for QR login, "
                        "then retry the company lookup once."
                    ),
                    blocked_reason="",
                )
                print("[login-required] QCC stayed on or redirected to the login page during company lookup.")
                print(f"[result-screenshot] {result_screenshot}")
                print(f"[visible-text] {text_path}")
                print(f"[latest-log] {latest_log_path}")
                print(f"[preview-html] {latest_log_path.with_suffix('.html')}")
                if not wait_for_login_checkpoint(
                    page=page,
                    timeout_seconds=args.login_timeout,
                    log_path=run_log_path,
                    latest_log_path=latest_log_path,
                    latest_json_path=latest_json_path,
                    company_name=args.company_name,
                    login_screenshot=login_screenshot,
                    result_screenshot=result_screenshot,
                    status_on_timeout="login_not_detected_after_search_redirect",
                    note_on_timeout=(
                        f"QCC required login during company lookup, and QR login was not detected within {args.login_timeout} seconds. "
                        "No company information was queried."
                    ),
                ):
                    return
                login_redirect_retries += 1
                print("[login] retrying company lookup after login detection.")

            if blocked_reason:
                write_run_log(
                    log_path=run_log_path,
                    latest_log_path=latest_log_path,
                    latest_json_path=latest_json_path,
                    company_name=args.company_name,
                    login_screenshot=login_screenshot,
                    result_screenshot=result_screenshot,
                    draft_json_path=None,
                    status="blocked",
                    note="QCC showed an access-control or verification page. No company_check draft was generated.",
                    blocked_reason=blocked_reason,
                )
                print(f"[blocked] {blocked_reason}")
                print("Stop here. Do not bypass login, captcha, WAF, paywalls, or access controls.")
                print(f"[result-screenshot] {result_screenshot}")
                print(f"[visible-text] {text_path}")
                print(f"[latest-log] {latest_log_path}")
                print(f"[preview-html] {latest_log_path.with_suffix('.html')}")
                return

            if args.company_name not in visible_text:
                write_run_log(
                    log_path=run_log_path,
                    latest_log_path=latest_log_path,
                    latest_json_path=latest_json_path,
                    company_name=args.company_name,
                    login_screenshot=login_screenshot,
                    result_screenshot=result_screenshot,
                    draft_json_path=None,
                    status="company_not_found_or_not_opened",
                    note=(
                        "QCC did not show the target company name in visible page text. "
                        "No company_check draft was generated to avoid extracting unrelated footer or navigation text."
                    ),
                    blocked_reason=blocked_reason,
                )
                print("[company-not-found] Target company name was not visible on the captured QCC page.")
                print("[qcc] No company verification data was obtained; do not report QCC verification as successful.")
                print(f"[result-screenshot] {result_screenshot}")
                print(f"[visible-text] {text_path}")
                print(f"[latest-log] {latest_log_path}")
                print(f"[preview-html] {latest_log_path.with_suffix('.html')}")
                return

            draft = build_company_check_draft(args.company_name, visible_text, result_screenshot, blocked_reason)
            draft_json_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
            write_run_log(
                log_path=run_log_path,
                latest_log_path=latest_log_path,
                latest_json_path=latest_json_path,
                company_name=args.company_name,
                login_screenshot=login_screenshot,
                result_screenshot=result_screenshot,
                draft_json_path=draft_json_path,
                status="blocked" if blocked_reason else "company_page_captured",
                note="Company page capture is a demo draft and must be manually verified before use.",
                blocked_reason=blocked_reason,
            )

            print(f"[result-screenshot] {result_screenshot}")
            print(f"[visible-text] {text_path}")
            print(f"[draft-json] {draft_json_path}")
            print(f"[run-log] {run_log_path}")
            print(f"[latest-log] {latest_log_path}")
            print(f"[preview-html] {latest_log_path.with_suffix('.html')}")

            print("[done] Demo finished. Please manually verify the draft fields before using them in contract review.")
        finally:
            context.close()


def find_chrome() -> Path | None:
    import sys as _sys
    if _sys.platform.startswith("linux"):
        for cand in [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
        ]:
            if cand.exists():
                return cand
        return None
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def wait_for_login_checkpoint(
    *,
    page: Any,
    timeout_seconds: int,
    log_path: Path,
    latest_log_path: Path,
    latest_json_path: Path,
    company_name: str,
    login_screenshot: Path,
    result_screenshot: Path | None,
    status_on_timeout: str,
    note_on_timeout: str,
) -> bool:
    print(f"[login] Waiting up to {timeout_seconds} seconds for QR login before company search.")
    login_detected = wait_for_probable_login(page, timeout_seconds)
    if login_detected:
        print("[login] probable login detected; continuing to company search.")
        return True

    write_run_log(
        log_path=log_path,
        latest_log_path=latest_log_path,
        latest_json_path=latest_json_path,
        company_name=company_name,
        login_screenshot=login_screenshot,
        result_screenshot=result_screenshot,
        draft_json_path=None,
        status=status_on_timeout,
        note=note_on_timeout,
        blocked_reason="",
    )
    print("[login] login was not detected before timeout; stop without querying company information.")
    print(f"[latest-log] {latest_log_path}")
    print(f"[preview-html] {latest_log_path.with_suffix('.html')}")
    return False


def open_qcc_home(page: Any) -> None:
    import time as _t
    try:
        page.goto(QCC_HOME, wait_until="commit", timeout=45000)
    except Exception as e:
        print(f"[warn] goto error: {e}", flush=True)
    _t.sleep(3.0)


def is_probably_logged_in(page: Any) -> bool:
    text = get_visible_text(page)
    if detect_blocked_reason(text):
        return False
    return has_logged_in_marker(text)


def has_logged_in_marker(text: str) -> bool:
    normalized = " ".join((text or "").split())
    if not normalized or is_qcc_login_page(normalized):
        return False
    if "退出" in normalized:
        return True

    logged_out_markers = ["免费注册", "扫码登录", "微信登录", "短信/密码登录", "打开 企查查APP"]
    if any(marker in normalized for marker in logged_out_markers):
        return False

    weak_logged_in_markers = ["消息", "会员中心", "个人中心", "我的企业", "我的关注"]
    marker_count = sum(1 for marker in weak_logged_in_markers if marker in normalized)
    return marker_count >= 2


def open_qcc_login(page: Any) -> None:
    open_qcc_home(page)

    for selector in [
        "text=登录",
        "a:has-text('登录')",
        "button:has-text('登录')",
        ".login",
    ]:
        try:
            target = page.locator(selector).first
            if target.count() and target.is_visible(timeout=1500):
                target.click(timeout=3000)
                __import__("time").sleep(3.0)
                return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    for url in QCC_LOGIN_CANDIDATES:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            __import__("time").sleep(3.0)
            return
        except Exception:
            continue


def wait_for_probable_login(page: Any, timeout_seconds: int) -> bool:
    deadline = time.time() + max(timeout_seconds, 1)
    while time.time() < deadline:
        text = get_visible_text(page)
        blocked = detect_blocked_reason(text)
        if blocked:
            print(f"[blocked-during-login] {blocked}")
            return False
        if has_logged_in_marker(text):
            return True
        __import__("time").sleep(3.0)
    return False


def search_company(page: Any, company_name: str) -> Any:
    page.goto(QCC_HOME, wait_until="domcontentloaded", timeout=45000)
    __import__("time").sleep(2.0)
    if is_qcc_login_page(get_visible_text(page)):
        return page

    input_selectors = [
        "input[placeholder*='请输入']",
        "input[placeholder*='查公司']",
        "input[placeholder*='企业名']",
        "input[type='text']",
        "textarea",
    ]
    for selector in input_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible(timeout=1500):
                loc.fill(company_name, timeout=3000)
                loc.press("Enter", timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=45000)
                __import__("time").sleep(3.0)
                return open_exact_company_result(page, company_name)
        except Exception:
            continue
    raise RuntimeError("Could not find a visible QCC search input. Stop and check the page manually.")


def open_company_detail_url(page: Any, company_url: str) -> Any:
    if not is_allowed_qcc_detail_url(company_url):
        raise RuntimeError("Only qcc.com /firm/*.html detail URLs are accepted for company-url.")
    page.goto(company_url, wait_until="domcontentloaded", timeout=45000)
    __import__("time").sleep(5.0)
    return page


def is_allowed_qcc_detail_url(company_url: str) -> bool:
    return bool(re.match(r"^https://(?:www\.)?qcc\.com/firm/[0-9A-Za-z]+\.html(?:[?#].*)?$", company_url.strip()))


def open_exact_company_result(page: Any, company_name: str) -> Any:
    """Open the visible exact company result when QCC returns a result list."""
    text = get_visible_text(page)
    if detect_blocked_reason(text):
        return page

    detail_href = find_exact_company_detail_href(page, company_name)
    if detail_href:
        page.goto(detail_href, wait_until="domcontentloaded", timeout=45000)
        __import__("time").sleep(4.0)
        return page

    selectors = [
        f"a[href*='/firm/']:has-text('{company_name}')",
        f"a:has-text('{company_name}')",
        f"text={company_name}",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible(timeout=2000):
                try:
                    with page.expect_popup(timeout=7000) as popup_info:
                        loc.click(timeout=5000)
                    popup = popup_info.value
                    popup.wait_for_load_state("domcontentloaded", timeout=45000)
                    popup.wait_for_timeout(4000)
                    return popup
                except Exception:
                    pass
                try:
                    with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
                        loc.click(timeout=5000)
                    __import__("time").sleep(4.0)
                    return page
                except Exception:
                    pass
                loc.click(timeout=5000)
                __import__("time").sleep(3.0)
                return page
        except Exception:
            continue
    return page


def find_exact_company_detail_href(page: Any, company_name: str) -> str:
    """Find the exact company's QCC detail URL from visible result anchors."""
    try:
        href = page.evaluate(
            """
            (companyName) => {
              const anchors = Array.from(document.querySelectorAll("a[href*='/firm/']"));
              for (const anchor of anchors) {
                const text = (anchor.innerText || anchor.textContent || '').replace(/\\s+/g, '');
                const normalized = String(companyName).replace(/\\s+/g, '');
                const href = anchor.href || anchor.getAttribute('href') || '';
                if (text === normalized && href.includes('/firm/')) return href;
              }
              for (const anchor of anchors) {
                const text = (anchor.innerText || anchor.textContent || '').replace(/\\s+/g, '');
                const normalized = String(companyName).replace(/\\s+/g, '');
                const href = anchor.href || anchor.getAttribute('href') || '';
                if (text.includes(normalized) && href.includes('/firm/')) return href;
              }
              return '';
            }
            """,
            company_name,
        )
        return str(href or "")
    except Exception:
        return ""


def get_visible_text(page: Any) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000)
    except Exception:
        return ""


def detect_blocked_reason(text: str) -> str:
    for keyword in BLOCK_KEYWORDS:
        if keyword in text:
            return f"QCC page contains access-control keyword: {keyword}"
    for pattern in ACCESS_BLOCK_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return f"QCC page contains access-control pattern: {pattern}"
    return ""


def is_qcc_login_page(text: str) -> bool:
    # v6: hardened login detection
    normalized = " ".join((text or "").split())
    if not normalized:
        return False
    # Positive markers: if any present, user is logged in -> NOT a login page.
    logged_in_markers = [
        "退出登录", "我的账号", "我的关注", "我的报告", "我的笔记", "我的VIP",
        "个人中心", "账户设置", "认领企业", "已认证", "已实名",
        "我的订单", "我的会员",
    ]
    if any(m in normalized for m in logged_in_markers):
        return False
    if ("统一社会信用代码" in normalized
        and any(st in normalized for st in ("存续", "在业", "正常", "开业"))):
        return False
    login_markers = ["扫码登录", "微信登录", "短信/密码登录", "打开 企查查APP"]
    marker_count = sum(1 for marker in login_markers if marker in normalized)
    if marker_count >= 2:
        return True
    return "扫码登录" in normalized and "免费注册" in normalized and "退出" not in normalized



# >>> qcc_card_v2 patch <<<
def _qcc_strip(s: str) -> str:
    """Strip QCC value: remove '复制', '更多 N', leading/trailing punctuation/spaces."""
    if not s:
        return ""
    s = s.replace("复制", "")
    s = re.sub(r"更多\s*\d*", "", s)
    s = s.strip(" \t\r\n：:|·,，")
    return s


def extract_qcc_card_fields_v2(company_name: str, visible_text: str) -> dict:
    """Parse a QCC search/detail page raw text into a structured dict.

    Handles QCC's two layouts:
    1. Inline:    "注册资本：4104113.182万元复制"
    2. Two-line:  "法定代表人：" then next non-empty line "赵明路"
    """
    if not visible_text:
        return {}

    raw_lines = visible_text.splitlines()
    # Locate card start: line containing the exact company_name (with optional status).
    status_words = "(?:存续|在业|正常|开业|在营|注销|吊销|迁出|停业|清算|已告解散)"
    head_pat = re.compile(rf"^\s*{re.escape(company_name)}(?:\s+{status_words})?\s*$")
    start = -1
    for idx, ln in enumerate(raw_lines):
        if head_pat.match(ln):
            start = idx
            break
    if start < 0:
        # Fallback: search for first occurrence of company_name + status_words
        for idx, ln in enumerate(raw_lines):
            if company_name in ln and re.search(status_words, ln):
                start = idx
                break
    if start < 0:
        return {}

    # End: stop at separator lines like 自身风险, 基本信息 X 法律诉讼, 简介:
    end_keywords = ("自身风险", "认领企业", "基本信息 ", "法律诉讼")
    end = len(raw_lines)
    for idx in range(start + 1, min(len(raw_lines), start + 80)):
        ln = raw_lines[idx]
        if any(k in ln for k in end_keywords):
            end = idx
            break
    card = raw_lines[start:end]

    # Helper: get value following a label, either inline (label：value) or next non-empty line.
    def value_for(labels: list, max_len: int = 200) -> str:
        for i, ln in enumerate(card):
            stripped = ln.strip()
            for label in labels:
                # Inline: label[：:](rest)
                m = re.match(rf"^\s*{re.escape(label)}\s*[：:]\s*(.+)$", stripped)
                if m:
                    val = _qcc_strip(m.group(1))
                    if val:
                        return val[:max_len]
                # Label-only line: next non-empty value line
                if re.match(rf"^\s*{re.escape(label)}\s*[：:]?\s*$", stripped):
                    for j in range(i + 1, min(len(card), i + 5)):
                        nxt = _qcc_strip(card[j])
                        if not nxt:
                            continue
                        # Skip pure noise
                        if nxt in {"复制", "详情", "导出"} or re.match(r"^更多\s*\d*$", nxt):
                            continue
                        return nxt[:max_len]
        return ""

    fields: dict = {}
    fields["name"] = company_name
    # company_status from header line
    header = card[0] if card else ""
    m = re.search(status_words, header)
    fields["company_status"] = m.group(0) if m else ""
    # credit_code: 18-char alphanumeric
    joined = "\n".join(card)
    m = re.search(r"(?:统一社会信用代码|信用代码)\s*[：:]?\s*([0-9A-Z]{18})", joined)
    fields["credit_code"] = m.group(1) if m else ""

    fields["legal_rep"] = value_for(["法定代表人", "法人代表"], max_len=20)
    # legal_rep should be a Chinese/Latin name 2-12 chars; trim if longer
    if fields["legal_rep"]:
        m2 = re.match(r"^([\u4e00-\u9fa5A-Za-z·]{2,12})", fields["legal_rep"])
        fields["legal_rep"] = m2.group(1) if m2 else fields["legal_rep"]

    fields["registered_address"] = value_for(["地址", "注册地址", "住所", "企业地址"], max_len=160)
    fields["registered_capital"] = value_for(["注册资本"], max_len=60)
    fields["established_date"] = value_for(["成立日期", "成立时间"], max_len=30)
    fields["phone"] = value_for(["电话", "联系电话"], max_len=40)
    fields["email"] = value_for(["邮箱", "电子邮箱"], max_len=80)
    fields["website"] = value_for(["官网", "网址"], max_len=120)
    fields["company_scale"] = value_for(["企业规模"], max_len=30)
    fields["employee_count"] = value_for(["员工人数", "参保人数"], max_len=40)
    # Industry: use first inline 企查查行业:value
    m = re.search(r"企查查行业\s*[：:]\s*([^\n\r]{2,40})", joined)
    fields["industry"] = _qcc_strip(m.group(1)) if m else ""
    # company_type / business_scope: keep empty unless visible
    fields["company_type"] = value_for(["企业类型", "公司类型"], max_len=80)
    fields["business_scope"] = value_for(["经营范围"], max_len=400)

    fields["extraction_mode"] = "qcc_card_v2"
    fields["_card_text"] = joined
    return fields
# >>> end qcc_card_v2 patch <<<

def _normalize_company_name(name: str) -> str:
    """Drop all whitespace from a Chinese company name. PDF text extraction
    sometimes inserts a space inside Chinese tokens ("华为技术有限公 司"),
    which breaks exact substring matching against the QCC page."""
    return re.sub(r"\s+", "", name or "")


def _name_visible_in(company_name: str, visible_text: str) -> bool:
    """Whitespace-tolerant company-name presence check."""
    if not company_name or not visible_text:
        return False
    if company_name in visible_text:
        return True
    return _normalize_company_name(company_name) in _normalize_company_name(visible_text)


def build_company_check_draft(
    company_name: str,
    visible_text: str,
    screenshot: Path,
    blocked_reason: str,
) -> dict[str, Any]:
    target_company_visible = bool(
        visible_text
        and _name_visible_in(company_name, visible_text)
        and not is_qcc_login_page(visible_text)
    )
    if not target_company_visible:
        registry_fields = {
            "name": "",
            "company_status": "",
            "credit_code": "",
            "legal_rep": "",
            "registered_address": "",
            "company_type": "",
            "business_scope": "",
            "extraction_mode": "no_target_company_visible",
        }
    else:
        # Try v2 robust parser first; fall back to legacy if it returned little.
        v2 = extract_qcc_card_fields_v2(company_name, visible_text)
        legacy = extract_company_registry_fields(company_name, visible_text)
        # Merge: v2 values win when truthy; otherwise fallback to legacy.
        registry_fields = dict(legacy)
        for k, v in v2.items():
            if v:
                registry_fields[k] = v
        if v2:
            registry_fields["extraction_mode"] = "qcc_card_v2"
    military_hits = (
        [kw for kw in ["军工", "国防", "兵器", "军事", "涉密", "武器装备"] if kw in visible_text]
        if target_company_visible
        else []
    )
    if target_company_visible:
        extracted_name = registry_fields.get("name") or company_name or first_labeled_match(
            visible_text,
            ["企业名称", "公司名称", "名称"],
            max_len=80,
        )
    else:
        extracted_name = ""
    related_people = (
        extract_related_people(registry_fields, visible_text)
        if target_company_visible
        else {"shareholders": [], "directors": [], "executives": []}
    )
    fallback_credit_code = ""
    fallback_legal_rep = ""
    fallback_registered_address = ""
    fallback_company_status = ""
    fallback_company_type = ""
    fallback_business_scope = ""
    if target_company_visible:
        fallback_credit_code = first_match(visible_text, r"(?:统一社会信用代码|信用代码)[：:\s]*([0-9A-Z]{18})")
        fallback_credit_code = fallback_credit_code or first_match(visible_text, r"\b[0-9A-Z]{18}\b")
        fallback_legal_rep = first_labeled_match(visible_text, ["法定代表人", "法人代表", "法人"], max_len=30)
        fallback_registered_address = first_labeled_match(visible_text, ["注册地址", "住所", "企业地址", "地址"], max_len=120)
        fallback_company_status = first_labeled_match(visible_text, ["登记状态", "经营状态", "状态"], max_len=20)
        fallback_company_status = fallback_company_status or first_match(
            visible_text, r"(存续|在业|正常|开业|在营|注销|吊销|迁出|停业|清算)"
        )
        fallback_company_type = first_labeled_match(visible_text, ["企业类型", "公司类型", "类型"], max_len=80)
        fallback_business_scope = first_labeled_match(visible_text, ["经营范围"], max_len=260)

    party_a = {
        "name": extracted_name,
        "credit_code": registry_fields.get("credit_code") or fallback_credit_code,
        "legal_rep": registry_fields.get("legal_rep") or fallback_legal_rep,
        "registered_address": registry_fields.get("registered_address") or fallback_registered_address,
        "company_status": registry_fields.get("company_status") or fallback_company_status,
        "company_type": registry_fields.get("company_type") or fallback_company_type,
        "business_scope": registry_fields.get("business_scope") or fallback_business_scope,
        "registered_capital": registry_fields.get("registered_capital", ""),
        "established_date": registry_fields.get("established_date", ""),
        "phone": registry_fields.get("phone", ""),
        "email": registry_fields.get("email", ""),
        "website": registry_fields.get("website", ""),
        "company_scale": registry_fields.get("company_scale", ""),
        "employee_count": registry_fields.get("employee_count", ""),
        "industry": registry_fields.get("industry", ""),
        "shareholders": related_people["shareholders"],
        "directors": related_people["directors"],
        "executives": related_people["executives"],
        "is_military_or_defense_related": True if military_hits else None,
        "military_or_defense_evidence": [f"企查查可见文本命中：{kw}" for kw in military_hits],
        "related_to_research_team": None,
        "related_person_matches": [],
    }
    return {
        "source": "企查查已登录浏览器可见页面演示结果（需人工复核）",
        "checked_at": datetime.now().strftime("%Y-%m-%d"),
        "evidence_files": [str(screenshot)],
        "blocked_reason": blocked_reason,
        "extraction_mode": registry_fields.get("extraction_mode", "generic_visible_text"),
        "party_a": party_a,
        "research_team": [],
        "demo_note": "This file is a draft generated from visible page text. Verify fields manually before using --company-check.",
    }


def extract_company_registry_fields(company_name: str, visible_text: str) -> dict[str, str]:
    """Extract fields from the exact-match QCC search-result card or detail text."""
    lines = [clean_extracted_value(line) for line in visible_text.splitlines()]
    lines = [line for line in lines if line]

    card = first_exact_company_card(company_name, lines)
    if card:
        card_text = "\n".join(card)
        first_line = card[0]
        return {
            "name": company_name,
            "company_status": first_match(first_line, r"(存续|在业|正常|开业|在营|注销|吊销|迁出|停业|清算|已告解散)"),
            "credit_code": first_match(card_text, r"(?:统一社会信用代码|信用代码)[：:\s]*([0-9A-Z]{18})"),
            "legal_rep": first_match(card_text, r"(?:法定代表人|法人代表|法人)[：:\s]*([\u4e00-\u9fa5A-Za-z·]{2,12})"),
            "registered_address": clean_extracted_value(
                first_match(card_text, r"(?:注册地址|住所|企业地址|地址)[：:\s]*([^\n\r|]{4,120})")
            ),
            "company_type": "",
            "business_scope": "",
            "extraction_mode": "qcc_exact_search_result_card",
            "_card_text": card_text,
        }

    text = "\n".join(lines)
    return {
        "name": _normalize_company_name(company_name) if _name_visible_in(company_name, text) else "",
        "company_status": first_labeled_match(text, ["登记状态", "经营状态", "状态"], max_len=20),
        "credit_code": first_match(text, r"(?:统一社会信用代码|信用代码)[：:\s]*([0-9A-Z]{18})"),
        "legal_rep": first_labeled_match(text, ["法定代表人", "法人代表", "法人"], max_len=30),
        "registered_address": first_labeled_match(text, ["注册地址", "住所", "企业地址", "地址"], max_len=120),
        "company_type": first_labeled_match(text, ["企业类型", "公司类型", "类型"], max_len=80),
        "business_scope": first_labeled_match(text, ["经营范围"], max_len=260),
        "extraction_mode": "qcc_generic_visible_text",
    }


def extract_related_people(registry_fields: dict[str, str], visible_text: str) -> dict[str, list[dict[str, str]]]:
    card_text = registry_fields.get("_card_text") or visible_text
    return {
        "shareholders": extract_named_people(card_text, ["股东"]),
        "directors": extract_named_people(card_text, ["董事长", "副董事长", "董事", "监事"]),
        "executives": extract_named_people(card_text, ["总经理", "经理", "高管", "负责人"]),
    }


def extract_named_people(text: str, titles: list[str]) -> list[dict[str, str]]:
    lines = [clean_extracted_value(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    people: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for idx, line in enumerate(lines):
        for title in titles:
            name = ""
            if line.startswith(f"{title}：") or line.startswith(f"{title}:"):
                name = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif line == title and idx + 1 < len(lines):
                name = lines[idx + 1].strip()
            elif line.startswith(title) and len(line) <= len(title) + 12:
                name = line[len(title) :].strip(" ：:")
            name = first_match(name, r"^[\u4e00-\u9fa5A-Za-z·]{2,12}") if name else ""
            if not name or name in {"更多", "复制", "主要分布"}:
                continue
            key = (title, name)
            if key in seen:
                continue
            seen.add(key)
            if title == "股东":
                people.append({"name": name, "type": title})
            else:
                people.append({"name": name, "title": title})
    return people[:20]


def first_exact_company_card(company_name: str, lines: list[str]) -> list[str]:
    status_words = "(?:存续|在业|正常|开业|在营|注销|吊销|迁出|停业|清算|已告解散)"
    exact_pattern = re.compile(rf"^{re.escape(company_name)}(?:\s+{status_words})?$")
    normalized_target = _normalize_company_name(company_name)
    norm_pattern = re.compile(rf"^{re.escape(normalized_target)}(?:\s*{status_words})?$") if normalized_target else None
    for idx, line in enumerate(lines):
        line_norm = _normalize_company_name(line)
        matched = exact_pattern.match(line) or (norm_pattern and norm_pattern.match(line_norm))
        if not matched:
            continue
        if any(suffix in line.replace(company_name, "", 1) for suffix in ["分公司", "研究所", "办事处"]):
            continue
        end = min(len(lines), idx + 40)
        for cursor in range(idx + 1, end):
            if "基本信息" in lines[cursor] and "法律诉讼" in lines[cursor]:
                end = cursor
                break
        return lines[idx:end]
    return []


def write_run_log(
    *,
    log_path: Path,
    latest_log_path: Path,
    latest_json_path: Path,
    company_name: str,
    login_screenshot: Path,
    result_screenshot: Path | None,
    draft_json_path: Path | None,
    status: str,
    note: str,
    blocked_reason: str,
) -> None:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    preview_html_path = log_path.with_suffix(".html")
    latest_preview_html_path = latest_log_path.with_suffix(".html")
    payload = {
        "demo": "qcc_login_demo",
        "checked_at": checked_at,
        "company_name": company_name,
        "status": status,
        "login_screenshot": str(login_screenshot),
        "result_screenshot": str(result_screenshot) if result_screenshot else "",
        "preview_html": str(preview_html_path),
        "latest_preview_html": str(latest_preview_html_path),
        "draft_json": str(draft_json_path) if draft_json_path else "",
        "blocked_reason": blocked_reason,
        "note": note,
    }
    latest_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 企查查二维码登录 Demo 记录",
        "",
        f"- 触发时间：{checked_at}",
        f"- 公司名称：{company_name}",
        f"- 状态：{status}",
        f"- 登录二维码截图：{login_screenshot}",
        f"- 本次预览页：{preview_html_path}",
        f"- 最新预览页：{latest_preview_html_path}",
    ]
    if result_screenshot:
        lines.append(f"- 查询页面截图：{result_screenshot}")
    if draft_json_path:
        lines.append(f"- 草稿核验文件：{draft_json_path}")
    if blocked_reason:
        lines.append(f"- 访问限制提示：{blocked_reason}")
    lines.extend(
        [
            f"- 说明：{note}",
            "",
            "本记录仅用于本机流程测试，不表示已经完成企业信息核验。",
        ]
    )
    text = "\n".join(lines) + "\n"
    log_path.write_text(text, encoding="utf-8")
    latest_log_path.write_text(text, encoding="utf-8")

    preview_html = build_preview_html(
        checked_at=checked_at,
        company_name=company_name,
        status=status,
        login_screenshot=login_screenshot,
        result_screenshot=result_screenshot,
        draft_json_path=draft_json_path,
        blocked_reason=blocked_reason,
        note=note,
    )
    preview_html_path.write_text(preview_html, encoding="utf-8")
    latest_preview_html_path.write_text(preview_html, encoding="utf-8")


def build_preview_html(
    *,
    checked_at: str,
    company_name: str,
    status: str,
    login_screenshot: Path,
    result_screenshot: Path | None,
    draft_json_path: Path | None,
    blocked_reason: str,
    note: str,
) -> str:
    image_cards = [
        build_image_card("登录二维码截图", login_screenshot),
    ]
    if result_screenshot:
        image_cards.append(build_image_card("查询页面截图", result_screenshot))

    draft_line = (
        f"<p><strong>草稿核验文件：</strong><code>{html.escape(str(draft_json_path))}</code></p>"
        if draft_json_path
        else ""
    )
    blocked_line = (
        f"<p class=\"warn\"><strong>访问限制提示：</strong>{html.escape(blocked_reason)}</p>"
        if blocked_reason
        else ""
    )
    cards_html = "\n".join(image_cards)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>企查查截图预览</title>
  <style>
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      color: #1f2933;
      background: #f6f8fb;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 24px 40px;
    }}
    h1 {{
      margin: 0 0 14px;
      font-size: 24px;
      font-weight: 650;
    }}
    .meta {{
      margin: 0 0 20px;
      line-height: 1.7;
      color: #384454;
    }}
    code {{
      word-break: break-all;
      white-space: normal;
      background: #eef2f7;
      padding: 2px 5px;
      border-radius: 4px;
    }}
    .warn {{
      color: #9a3412;
      background: #fff7ed;
      border-left: 4px solid #fb923c;
      padding: 10px 12px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
    }}
    .card {{
      background: #ffffff;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      padding: 14px;
    }}
    .card h2 {{
      margin: 0 0 10px;
      font-size: 17px;
    }}
    img {{
      display: block;
      width: 100%;
      height: auto;
      border: 1px solid #d9e2ec;
      border-radius: 6px;
      background: #fff;
    }}
    .missing {{
      padding: 18px;
      background: #f8fafc;
      border: 1px dashed #b8c4d0;
      color: #5b6776;
    }}
    .foot {{
      margin-top: 24px;
      color: #5b6776;
      font-size: 14px;
    }}
  </style>
</head>
<body>
<main>
  <h1>企查查截图预览</h1>
  <section class="meta">
    <p><strong>触发时间：</strong>{html.escape(checked_at)}</p>
    <p><strong>公司名称：</strong>{html.escape(company_name)}</p>
    <p><strong>状态：</strong>{html.escape(status)}</p>
    {draft_line}
    {blocked_line}
    <p><strong>说明：</strong>{html.escape(note)}</p>
  </section>
  <section class="grid">
    {cards_html}
  </section>
  <p class="foot">本页仅用于本机流程测试和截图查看，不表示已经完成企业信息核验。</p>
</main>
</body>
</html>
"""


def build_image_card(title: str, image_path: Path) -> str:
    data_uri = image_data_uri(image_path)
    path_text = html.escape(str(image_path))
    if not data_uri:
        body = f"<div class=\"missing\">未找到截图文件：<code>{path_text}</code></div>"
    else:
        body = f"<img alt=\"{html.escape(title)}\" src=\"{data_uri}\">"
    return f"""<article class="card">
  <h2>{html.escape(title)}</h2>
  {body}
  <p><code>{path_text}</code></p>
</article>"""


def image_data_uri(image_path: Path) -> str:
    if not image_path.exists():
        return ""
    suffix = image_path.suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    if not match:
        return ""
    if match.lastindex:
        return match.group(1).strip()
    return match.group(0).strip()


def first_labeled_match(text: str, labels: list[str], max_len: int) -> str:
    for label in labels:
        patterns = [
            rf"{re.escape(label)}[：:\s]*([^\n\r]{{1,{max_len}}})",
            rf"{re.escape(label)}\s*[\n\r]+\s*([^\n\r]{{1,{max_len}}})",
        ]
        for pattern in patterns:
            value = first_match(text, pattern)
            value = clean_extracted_value(value)
            if value and value not in labels:
                return value
    return ""


def clean_extracted_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" ：:\t\r\n")
    noise_prefixes = ["更多", "查看", "复制", "详情", "导出"]
    for prefix in noise_prefixes:
        if value.startswith(prefix):
            return ""
    value = value.replace("复制", "").strip(" ：:\t\r\n")
    noise_values = {
        "企业名",
        "经营范围",
        "企业简介",
        "地址",
        "品牌",
        "法定代表人",
        "专利",
        "商标",
        "登记状态",
        "注册资本",
        "实缴资本",
        "成立日期",
    }
    if value in noise_values:
        return ""
    return value.strip()


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", name, flags=re.UNICODE).strip("_")
    return cleaned or "company"


if __name__ == "__main__":
    if sys.platform != "win32":
        print("[warn] This demo was written for local desktop browser testing; Windows + Chrome is recommended.")
    main()
