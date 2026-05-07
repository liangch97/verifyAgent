from __future__ import annotations

import argparse
from pathlib import Path

from .config import OUTPUT_DIR, RULES_PATH
from .company_check_loader import load_company_check
from .contract_extractor import extract_contract
from .contract_loader import load_contract
from .contract_report_writer import write_outputs
from .contract_rule_checker import check_contract, load_rules
from .template_matcher import detect_template_match
from .utils import file_hash


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="中山大学横向合同形式化审核")
    p.add_argument("input", type=Path, help="合同文件路径（.docx/.pdf/.txt）")
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    p.add_argument("--rules", type=Path, default=RULES_PATH)
    p.add_argument("--company-check", type=Path, default=None, help="外部工商/关联关系核验文件（.json/.csv/.xlsx）")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"文件不存在: {args.input}")
    if args.company_check and not args.company_check.exists():
        raise SystemExit(f"company_check 文件不存在: {args.company_check}")

    loaded = load_contract(args.input)
    extracted = extract_contract(loaded)
    extracted["source_hash"] = file_hash(args.input)

    # Template-based contract detection (range over school templates).
    try:
        template_match = detect_template_match(
            extracted.get("full_text", "") or "\n".join(b.get("text", "") for b in loaded.get("ordered_blocks", [])),
            contract_path=args.input,
        )
    except Exception as exc:  # noqa: BLE001
        template_match = {"matched": False, "reason": f"detect_failed:{exc}"}
    extracted["template_match"] = template_match

    company_check = None
    if args.company_check:
        company_check = load_company_check(args.company_check)

    rules = load_rules(args.rules)
    review = check_contract(extracted, rules, company_check=company_check)
    review["template_match"] = template_match

    paths = write_outputs(review, args.output_dir, extracted["source_hash"])
    print(f"[done] decision={review['decision']} confidence={review['confidence']}")
    print(f"[md] {paths['markdown']}")
    print(f"[json] {paths['json']}")
    print(f"[xlsx] {paths['excel']}")


if __name__ == "__main__":
    main()
