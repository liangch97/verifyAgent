from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
REFERENCES_DIR = ROOT / "references"
RULES_PATH = REFERENCES_DIR / "rules" / "horizontal_contract_formal_rules.yaml"
SCHEMA_CASE_PATH = REFERENCES_DIR / "schemas" / "contract_case.json"
SCHEMA_REVIEW_PATH = REFERENCES_DIR / "schemas" / "contract_review.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
