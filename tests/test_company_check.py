from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.company_check_loader import load_company_check
from scripts.company_check_matcher import check_related_party
from scripts.contract_extractor import extract_contract
from scripts.contract_loader import load_contract
from scripts.contract_report_writer import write_outputs
from scripts.contract_rule_checker import check_contract, load_rules


ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "references" / "rules" / "horizontal_contract_formal_rules.yaml"
SAMPLE_COMPANY_CHECK = ROOT / "samples" / "company_check_huawei.json"
SAMPLE_DOCX = ROOT / "samples" / "华为-中大智算集群可靠性测评技术合作协议-脱敏版.docx"


def _base_extracted(text: str) -> dict:
    return {
        "source_file": "dummy.docx",
        "title": "测试合同",
        "party_a": {
            "name": "华为技术有限公司",
            "address": "中国广东省深圳市龙岗区坂田华为总部办公楼",
            "legal_rep": "张三",
            "credit_code": "914403001922038216",
        },
        "party_b": {"name": "中山大学"},
        "project_name": "测试项目",
        "contract_type": "技术合作协议",
        "amount": "100万元",
        "payment_terms": ["合同生效后10日内支付首付款"],
        "concrete_payment_terms": ["合同生效后10日内支付首付款"],
        "bank_account": {
            "name": "中山大学",
            "account": "44050143004609000001",
            "bank": "中国建设银行广州中山大学支行",
        },
        "contacts": [],
        "sections": [],
        "attachments": [],
        "missing_referenced_attachments": [],
        "dates": [],
        "ip_clauses": [],
        "confidentiality_clauses": [],
        "liability_clauses": [],
        "dispute_resolution": "",
        "blanks": [],
        "raw_text_excerpt": text[:200],
        "comments": [],
        "highlights": [],
        "full_text": text,
    }


def _find_by_rule(review: dict, rule_id: str) -> list[dict]:
    return [f for f in review["findings"] if f.get("rule_id") == rule_id]


def test_company_check_json_can_be_loaded():
    payload = load_company_check(SAMPLE_COMPANY_CHECK)
    assert payload["source"]
    assert payload["checked_at"]
    assert payload["party_a"]["name"] == "华为技术有限公司"


def test_company_check_csv_can_be_loaded():
    out_dir = ROOT / "output" / "pytest-company-inputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "company_check.csv"
    csv_path.write_text(
        "source,checked_at,party_a.name,party_a.credit_code,party_a.related_to_research_team,evidence_files\n"
        "人工核验,2026-04-24,华为技术有限公司,914403001922038216,false,D:/evidence/a.pdf、D:/evidence/b.pdf\n",
        encoding="utf-8",
    )
    payload = load_company_check(csv_path)
    assert payload["source"] == "人工核验"
    assert payload["party_a"]["credit_code"] == "914403001922038216"
    assert payload["party_a"]["related_to_research_team"] is False
    assert len(payload["evidence_files"]) == 2


def test_related_party_message_when_only_research_team_missing():
    result = check_related_party(
        {
            "party_a": {
                "legal_rep": "赵明路",
                "shareholders": [{"name": "华为投资控股有限公司", "type": "股东"}],
                "directors": [{"name": "梁华", "title": "董事长"}],
                "executives": [],
            },
            "research_team": [],
        }
    )

    assert result["status"] == "insufficient_info"
    assert result["company_personnel_provided"] is True
    assert "缺少课题组成员名单" in result["message"]
    assert "外部核验信息不足" not in result["message"]


def test_company_check_xlsx_can_be_loaded():
    import openpyxl

    out_dir = ROOT / "output" / "pytest-company-inputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_dir / "company_check.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["source", "checked_at", "party_a.name", "party_a.company_status", "party_a.is_military_or_defense_related"])
    ws.append(["企查查", "2026-04-24", "华为技术有限公司", "存续", "false"])
    wb.save(xlsx_path)

    payload = load_company_check(xlsx_path)
    assert payload["source"] == "企查查"
    assert payload["party_a"]["company_status"] == "存续"
    assert payload["party_a"]["is_military_or_defense_related"] is False


def test_a1_name_match_not_in_findings_or_downgraded_to_info():
    rules = load_rules(RULES_PATH)
    extracted = _base_extracted("基于民用用途，不涉及国家秘密。")
    company_check = load_company_check(SAMPLE_COMPANY_CHECK)

    review = check_contract(extracted, rules, company_check=company_check)
    a1_hits = _find_by_rule(review, "A1_REVIEW")

    assert not a1_hits or all(item["severity"] == "info" for item in a1_hits)


def test_a1_credit_code_mismatch_should_block():
    rules = load_rules(RULES_PATH)
    extracted = _base_extracted("基于民用用途，不涉及国家秘密。")
    company_check = load_company_check(SAMPLE_COMPANY_CHECK)
    company_check = copy.deepcopy(company_check)
    company_check["party_a"]["credit_code"] = "999999999999999999"

    review = check_contract(extracted, rules, company_check=company_check)
    a1_hits = _find_by_rule(review, "A1_REVIEW")

    assert a1_hits
    assert a1_hits[0]["severity"] == "block"


def test_a2_related_to_research_team_should_warn_and_require_statement():
    rules = load_rules(RULES_PATH)
    extracted = _base_extracted("基于民用用途，不涉及国家秘密。")
    company_check = load_company_check(SAMPLE_COMPANY_CHECK)
    company_check = copy.deepcopy(company_check)
    company_check["party_a"]["related_to_research_team"] = True
    company_check["party_a"]["related_person_matches"] = ["陈壮彬"]

    review = check_contract(extracted, rules, company_check=company_check)
    a2_hits = _find_by_rule(review, "A2")

    assert a2_hits
    assert a2_hits[0]["severity"] in {"warn", "block"}
    assert "声明" in a2_hits[0]["message"] or "声明" in a2_hits[0]["suggestion"]


def test_a2_no_relation_with_research_team_should_not_be_finding():
    rules = load_rules(RULES_PATH)
    extracted = _base_extracted("基于民用用途，不涉及国家秘密。")
    company_check = load_company_check(SAMPLE_COMPANY_CHECK)
    company_check = copy.deepcopy(company_check)
    company_check["party_a"]["related_to_research_team"] = False
    company_check["party_a"]["related_person_matches"] = []
    company_check["research_team"] = [{"name": "陈壮彬", "role": "项目负责人"}]

    review = check_contract(extracted, rules, company_check=company_check)
    assert not _find_by_rule(review, "A2")


def test_a3_military_related_should_warn_or_block():
    rules = load_rules(RULES_PATH)
    extracted = _base_extracted("基于民用用途，不涉及国家秘密。")
    company_check = load_company_check(SAMPLE_COMPANY_CHECK)
    company_check = copy.deepcopy(company_check)
    company_check["party_a"]["is_military_or_defense_related"] = True
    company_check["party_a"]["military_or_defense_evidence"] = ["企业公开信息：军工配套单位"]

    review = check_contract(extracted, rules, company_check=company_check)
    a3_hits = _find_by_rule(review, "A3")

    assert a3_hits
    assert a3_hits[0]["severity"] in {"warn", "block"}


def test_without_company_check_a1_a2_a3_should_remain_review():
    rules = load_rules(RULES_PATH)
    extracted = _base_extracted("普通合同文本")
    review = check_contract(extracted, rules)

    ids = {f["rule_id"] for f in review["findings"] if f.get("scope") == "review"}
    assert {"A1_REVIEW", "A2", "A3"}.issubset(ids)


def test_sample_contract_with_company_check_can_output_markdown_and_json():
    if not SAMPLE_DOCX.exists() or not SAMPLE_COMPANY_CHECK.exists():
        import pytest

        pytest.skip("sample files not found")

    loaded = load_contract(SAMPLE_DOCX)
    extracted = extract_contract(loaded)
    rules = load_rules(RULES_PATH)
    company_check = load_company_check(SAMPLE_COMPANY_CHECK)

    review = check_contract(extracted, rules, company_check=company_check)
    outputs = write_outputs(review, ROOT / "output" / "pytest-company-check", "companycheck")

    assert Path(outputs["markdown"]).exists()
    assert Path(outputs["json"]).exists()

    md_text = Path(outputs["markdown"]).read_text(encoding="utf-8")
    assert "## 外部核验材料" in md_text

    review_json = json.loads(Path(outputs["json"]).read_text(encoding="utf-8"))
    assert review_json["external_checks"]["company_check_provided"] is True
