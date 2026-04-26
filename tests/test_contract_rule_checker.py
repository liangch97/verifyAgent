from __future__ import annotations

import os
from pathlib import Path

from scripts.contract_extractor import extract_contract
from scripts.contract_loader import load_contract
from scripts.contract_rule_checker import check_contract, load_rules
from scripts.contract_report_writer import write_outputs


ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "references" / "rules" / "horizontal_contract_formal_rules.yaml"
SAMPLE_DOCX = ROOT / "samples" / "华为-中大智算集群可靠性测评技术合作协议-脱敏版.docx"


def _base_extracted(text: str) -> dict:
    return {
        "source_file": "dummy.docx",
        "title": "测试合同",
        "party_a": {"name": "甲方公司"},
        "party_b": {"name": "中山大学"},
        "project_name": "测试项目",
        "contract_type": "技术开发合同",
        "amount": "100万元",
        "payment_terms": ["合同生效后10日内支付首付款"],
        "bank_account": {"name": "中山大学", "account": "44050143004609000001", "bank": "中国建设银行广州中山大学支行"},
        "contacts": [],
        "sections": [],
        "attachments": [],
        "dates": [],
        "ip_clauses": [],
        "confidentiality_clauses": [],
        "liability_clauses": [],
        "dispute_resolution": "",
        "blanks": [],
        "raw_text_excerpt": text[:200],
        "comments": [],
        "full_text": text,
    }


def _find_by_rule(review: dict, rule_id: str) -> list[dict]:
    return [f for f in review["findings"] if f.get("rule_id") == rule_id]


def test_yaml_load_and_rule_ids_unique():
    rules = load_rules(RULES_PATH)
    assert len(rules) > 0
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids))


def test_not_checked_not_in_findings():
    rules = load_rules(RULES_PATH)
    review = check_contract(_base_extracted("普通文本"), rules)
    finding_ids = {f["rule_id"] for f in review["findings"]}
    for item in review["not_checked_items"]:
        assert item["rule_id"] not in finding_ids


def test_e3_confidentiality_hits_unlimited_longterm_and_six_years():
    rules = load_rules(RULES_PATH)

    ex1 = _base_extracted("保密期限为无限期")
    ex1["confidentiality_clauses"] = ["保密期限为无限期"]
    r1 = check_contract(ex1, rules)
    assert _find_by_rule(r1, "E3")

    ex2 = _base_extracted("保密义务长期有效")
    ex2["confidentiality_clauses"] = ["保密义务长期有效"]
    r2 = check_contract(ex2, rules)
    assert _find_by_rule(r2, "E3")

    ex3 = _base_extracted("保密期限6年")
    ex3["confidentiality_clauses"] = ["保密期限6年"]
    r3 = check_contract(ex3, rules)
    assert _find_by_rule(r3, "E3")


def test_e9_hits_guangzhou_city_arbitration_name():
    rules = load_rules(RULES_PATH)
    ex = _base_extracted("争议提交广州市仲裁委员会")
    ex["dispute_resolution"] = "争议提交广州市仲裁委员会"
    r = check_contract(ex, rules)
    assert _find_by_rule(r, "E9")


def test_e1_does_not_treat_calendar_year_as_duration():
    rules = load_rules(RULES_PATH)
    ex = _base_extracted("双方已经于2024年11月签署保密协议。")
    r = check_contract(ex, rules)
    assert not _find_by_rule(r, "E1")


def test_d1_d2_hit_when_ip_owned_by_party_a():
    rules = load_rules(RULES_PATH)
    ex = _base_extracted("知识产权归甲方所有")
    ex["ip_clauses"] = ["第2.3条 开发成果归甲方所有", "第4.2条 全部知识产权均归甲方所有"]
    r = check_contract(ex, rules)
    assert _find_by_rule(r, "D1")
    assert _find_by_rule(r, "D2")


def test_summary_stats_are_the_json_count_source():
    rules = load_rules(RULES_PATH)
    ex = _base_extracted("知识产权归甲方所有。争议由合同签署地法院管辖。")
    ex["party_b"]["name"] = "中山大学"
    ex["ip_clauses"] = ["4.2 本合同下产生的全部知识产权均归甲方所有。"]
    ex["dispute_resolution"] = "争议由合同签署地法院管辖。"
    review = check_contract(ex, rules)
    stats = review["summary_stats"]

    assert stats["findings_total"] == len(review["findings"])
    assert stats["risk_total"] == sum(
        1
        for finding in review["findings"]
        if finding.get("scope") == "enforce" and finding.get("severity") in {"block", "warn"}
    )
    assert stats["review_total"] == sum(1 for finding in review["findings"] if finding.get("scope") == "review")
    assert stats["info_total"] == sum(1 for finding in review["findings"] if finding.get("severity") == "info")
    assert stats["not_checked_total"] == len(review["not_checked_items"])


def test_d1_distinguishes_generated_ip_and_background_ip_use():
    rules = load_rules(RULES_PATH)
    ex = _base_extracted("知识产权归属。")
    ex["party_b"]["name"] = "中山大学"
    ex["ip_clauses"] = [
        "4.1 双方的背景知识产权归各自所有。",
        "4.2 本合同下产生的全部知识产权，包括专利权、版权、商业秘密，均归甲方所有。乙方理解并同意，甲方及其关联公司有权为使用全部或部分开发成果的目的而实施或委托第三方实施项目组成员前期产生的且使用开发成果所必须的乙方背景知识产权，使用背景知识产权的费用须包含在项目费用中，甲方无须在合同总金额外另行付费。",
    ]

    review = check_contract(ex, rules)
    d1 = _find_by_rule(review, "D1")[0]
    details = d1["details"]

    assert "本合同下产生的全部知识产权" in details["generated_ip_ownership"]
    assert "背景知识产权归各自所有" in details["background_ip_ownership"]
    assert "委托第三方实施" in details["background_ip_use_arrangement"]
    assert "不是所有权转移" in d1["message"]


def test_d3_only_applies_when_ip_is_shared():
    rules = load_rules(RULES_PATH)
    ex = _base_extracted("知识产权归甲方所有")
    ex["ip_clauses"] = ["第4.2条 全部知识产权均归甲方所有"]
    r = check_contract(ex, rules)
    assert not _find_by_rule(r, "D3")

    ex_shared = _base_extracted("知识产权归双方共有")
    ex_shared["ip_clauses"] = ["本项目知识产权归双方共有。"]
    r_shared = check_contract(ex_shared, rules)
    assert _find_by_rule(r_shared, "D3")


def test_e6_does_not_flag_existing_nda_definition():
    rules = load_rules(RULES_PATH)
    ex = _base_extracted("“保密协议”是指甲乙双方已经于2024年11月签署的《保密协议》。")
    r = check_contract(ex, rules)
    assert not _find_by_rule(r, "E6")


def test_missing_bank_account_with_missing_sow_is_warn_not_block():
    rules = load_rules(RULES_PATH)
    ex = _base_extracted("工作任务书见附件。")
    ex["bank_account"] = {"name": "", "account": "", "bank": ""}
    ex["missing_referenced_attachments"] = ["工作任务书/SOW"]
    r = check_contract(ex, rules)
    c1 = _find_by_rule(r, "C1")
    assert c1
    assert c1[0]["severity"] == "warn"
    assert "工作任务书/SOW" in c1[0]["evidence"]


def test_loader_extracts_comments_and_highlights_from_standard_docx():
    standard_env = os.environ.get("CONTRACT_REVIEW_STANDARD_DOCX")
    standard = Path(standard_env) if standard_env else ROOT / "samples" / "横向合同基本审核要点_科研秘书版20240111.docx"
    if not standard.exists():
        import pytest

        pytest.skip("standard docx not found")
    loaded = load_contract(standard)
    assert any("项目名称" in h.get("text", "") for h in loaded.get("highlights", []))
    assert any("豆包" in c.get("text", "") and c.get("anchor") for c in loaded.get("comments", []))


def test_c6_hits_when_surplus_returned_to_party_a():
    rules = load_rules(RULES_PATH)
    ex = _base_extracted("项目结余经费退回甲方")
    ex["full_text"] = "双方同意项目结余经费退回甲方。"
    r = check_contract(ex, rules)
    assert _find_by_rule(r, "C6")


def test_smoke_with_sample_docx_generates_markdown_and_json():
    if not SAMPLE_DOCX.exists():
        import pytest

        pytest.skip("sample docx not found")

    loaded = load_contract(SAMPLE_DOCX)
    extracted = extract_contract(loaded)
    rules = load_rules(RULES_PATH)
    review = check_contract(extracted, rules)
    out_dir = ROOT / "output" / "pytest-smoke"
    outputs = write_outputs(review, out_dir, "smoketest")

    assert Path(outputs["markdown"]).exists()
    assert Path(outputs["json"]).exists()

    md_text = Path(outputs["markdown"]).read_text(encoding="utf-8")
    assert "### 1.1 建议先修改的事项" in md_text
    assert "| 序号 | 事项 | 关联条款/证据 | 风险说明 | 建议处理 |" in md_text
