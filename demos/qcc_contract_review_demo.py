from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QCC_OUTPUT_DIR = ROOT / "output" / "qcc_login_demo"
DEFAULT_PROFILE_DIR = ROOT / ".browser-profiles" / "qcc-demo"
DEFAULT_LOGIN_TIMEOUT_SECONDS = 900
REVIEW_SCRIPT = ROOT / "run_contract_review.py"
QCC_SCRIPT = ROOT / "demos" / "qcc_login_demo.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.contract_extractor import extract_contract  # noqa: E402
from scripts.contract_loader import load_contract  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an explicit QCC QR-login company check, then rerun contract review with the generated company_check draft."
    )
    parser.add_argument("contract", type=Path, help="Contract file path")
    parser.add_argument("--company-name", default="", help="Override Party A company name. Default: extract from contract.")
    parser.add_argument(
        "--company-url",
        default="",
        help="Optional exact QCC detail URL, for example https://www.qcc.com/firm/xxx.html. Requires login first.",
    )
    parser.add_argument("--qcc-output-dir", type=Path, default=DEFAULT_QCC_OUTPUT_DIR)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument(
        "--reuse-profile",
        action="store_true",
        help="Reuse the browser profile so a previous QCC scan-login session can be reused on the same machine.",
    )
    parser.add_argument("--review-output-dir", type=Path, default=ROOT / "output")
    parser.add_argument(
        "--login-timeout",
        type=int,
        default=DEFAULT_LOGIN_TIMEOUT_SECONDS,
        help="Seconds to wait for QR login. Company search and contract review with QCC data only start after login is detected.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    contract = args.contract.resolve()
    if not contract.exists():
        raise SystemExit(f"合同文件不存在: {contract}")

    company_name = args.company_name.strip() or extract_party_a_name(contract)
    if not company_name:
        raise SystemExit("无法从合同中识别甲方公司名称；请使用 --company-name 手工指定。")

    log(f"[contract] {contract}")
    log(f"[company-name] {company_name}")
    if args.reuse_profile:
        log(f"[qcc] 将复用浏览器资料目录：{args.profile_dir}")
    log(f"[qcc] 请在弹出的企查查窗口扫码登录，最多等待 {args.login_timeout} 秒。若已复用登录状态，将直接跳过扫码。不会绕过登录、验证码、访问限制或付费内容。")

    run_qcc_demo(
        company_name=company_name,
        output_dir=args.qcc_output_dir,
        login_timeout=args.login_timeout,
        reuse_profile=args.reuse_profile,
        profile_dir=args.profile_dir,
        company_url=args.company_url,
    )
    manifest = load_latest_manifest(args.qcc_output_dir)
    draft_json_text = str(manifest.get("draft_json") or "").strip()
    draft_json = Path(draft_json_text) if draft_json_text else None

    if not draft_json or not draft_json.exists():
        log("[qcc] 未生成可用于审核的企业核验草稿。")
        log(f"[qcc-latest-log] {args.qcc_output_dir / 'qcc_login_demo_latest.md'}")
        log(f"[qcc-preview] {manifest.get('latest_preview_html') or args.qcc_output_dir / 'qcc_login_demo_latest.html'}")
        log("[review] 不使用企业核验材料，运行普通合同审核。")
        run_review(contract, args.review_output_dir, company_check=None)
        return

    if not is_usable_company_check(draft_json):
        log(f"[qcc-draft] {draft_json}")
        log(f"[qcc-preview] {manifest.get('latest_preview_html') or args.qcc_output_dir / 'qcc_login_demo_latest.html'}")
        log("[qcc] 企业核验草稿字段不足，不能作为自动核验依据。")
        log("[review] 不使用企业核验材料，运行普通合同审核。")
        run_review(contract, args.review_output_dir, company_check=None)
        return

    log(f"[company-check] {draft_json}")
    log(f"[qcc-latest-log] {args.qcc_output_dir / 'qcc_login_demo_latest.md'}")
    log(f"[qcc-preview] {manifest.get('latest_preview_html') or args.qcc_output_dir / 'qcc_login_demo_latest.html'}")
    log("[review] 使用企查查可见页面生成的核验草稿重新审核合同。")
    run_review(contract, args.review_output_dir, company_check=draft_json)


def extract_party_a_name(contract: Path) -> str:
    loaded = load_contract(contract)
    extracted = extract_contract(loaded)
    return str((extracted.get("party_a") or {}).get("name") or "").strip()


def run_qcc_demo(
    *,
    company_name: str,
    output_dir: Path,
    login_timeout: int,
    reuse_profile: bool,
    profile_dir: Path,
    company_url: str,
) -> None:
    cmd = [
        sys.executable,
        str(QCC_SCRIPT),
        company_name,
        "--output-dir",
        str(output_dir),
        "--profile-dir",
        str(profile_dir),
        "--login-timeout",
        str(login_timeout),
        "--require-login",
    ]
    if reuse_profile:
        cmd.append("--reuse-profile")
    if company_url:
        cmd.extend(["--company-url", company_url])
    completed = subprocess.run(cmd, cwd=str(ROOT), text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def load_latest_manifest(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "qcc_login_demo_latest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def is_usable_company_check(path: Path) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("blocked_reason") or "").strip():
        return False
    if str(payload.get("extraction_mode") or "").strip() == "no_target_company_visible":
        return False
    party_a = payload.get("party_a") or {}
    has_name = bool(str(party_a.get("name") or "").strip())
    has_core_registry_field = any(
        str(party_a.get(key) or "").strip()
        for key in ["credit_code", "legal_rep", "company_status"]
    )
    return has_name and has_core_registry_field


def run_review(contract: Path, output_dir: Path, company_check: Path | None) -> None:
    cmd = [
        sys.executable,
        str(REVIEW_SCRIPT),
        str(contract),
        "--output-dir",
        str(output_dir),
    ]
    if company_check:
        cmd.extend(["--company-check", str(company_check)])
    completed = subprocess.run(cmd, cwd=str(ROOT), text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def log(message: str) -> None:
    print(message, flush=True)


if __name__ == "__main__":
    main()
