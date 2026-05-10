from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .company_check_matcher import check_military_defense, check_related_party, compare_party_a
from .utils import normalize_spaces


def load_rules(path: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload.get("rules", [])


def check_contract(
    extracted: dict[str, Any],
    rules: list[dict[str, Any]],
    company_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    not_checked_items: list[dict[str, Any]] = []
    rule_results: list[dict[str, Any]] = []
    full_text = extracted.get("full_text", "")
    company_check_provided = company_check is not None
    external_checks = _build_external_checks(extracted, full_text, company_check)

    for rule in rules:
        scope = rule.get("scope")
        if scope == "not_checked" or rule.get("check_type") == "not_checked":
            item = _make_not_checked(rule)
            not_checked_items.append(item)
            rule_results.append(_make_rule_result(rule, "not_checked", item))
            continue

        check_type = rule.get("check_type")
        if check_type == "review_only":
            review_finding = _check_review_item(
                rule,
                extracted,
                full_text,
                external_checks=external_checks,
                company_check_provided=company_check_provided,
            )
            if review_finding:
                findings.append(review_finding)
                rule_results.append(_make_rule_result(rule, "hit", review_finding))
            else:
                rule_results.append(_make_rule_result(rule, "pass", None))
            continue

        result = _run_enforce_check(rule, extracted, full_text)
        if result:
            findings.append(result)
            rule_results.append(_make_rule_result(rule, "hit", result))
        else:
            rule_results.append(_make_rule_result(rule, "pass", None))

    decision = _map_decision(findings)
    summary_stats = _build_summary_stats(findings, not_checked_items, rule_results)
    return {
        "source_file": extracted.get("source_file", ""),
        "decision": decision["decision"],
        "confidence": decision["confidence"],
        "summary_stats": summary_stats,
        "findings": findings,
        "not_checked_items": not_checked_items,
        "rule_results": rule_results,
        "extracted": extracted,
        "external_checks": external_checks,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _make_not_checked(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": rule.get("id"),
        "section": rule.get("section"),
        "severity": "not_checked",
        "scope": "not_checked",
        "title": rule.get("title"),
        "message": rule.get("message"),
        "suggestion": rule.get("suggestion"),
        "source_text": rule.get("source_text", ""),
        "comment_guidance": rule.get("comment_guidance", ""),
    }


def _check_review_item(
    rule: dict[str, Any],
    extracted: dict[str, Any],
    text: str,
    external_checks: dict[str, Any],
    company_check_provided: bool,
) -> dict[str, Any] | None:
    if rule.get("id") in {"A1_REVIEW", "A2", "A3"}:
        return _check_external_review_item(rule, external_checks, company_check_provided)

    patterns = rule.get("patterns") or []
    evidence = _evidence_from_patterns(text, patterns) if patterns else "需人工复核"
    if not evidence:
        if not rule.get("always_review"):
            return None
        evidence = "需人工复核"
    return _make_finding(rule, evidence=evidence, location=_locate(text, evidence), confidence=0.55)


def _check_external_review_item(
    rule: dict[str, Any],
    external_checks: dict[str, Any],
    company_check_provided: bool,
) -> dict[str, Any] | None:
    if not company_check_provided:
        return _make_review_missing_external_finding(rule)

    rule_id = rule.get("id")
    if rule_id == "A1_REVIEW":
        return _build_a1_external_finding(rule, external_checks)
    if rule_id == "A2":
        return _build_a2_external_finding(rule, external_checks)
    if rule_id == "A3":
        return _build_a3_external_finding(rule, external_checks)
    return None


def _make_review_missing_external_finding(rule: dict[str, Any]) -> dict[str, Any]:
    r = dict(rule)
    r["message"] = f"未提供外部工商核验材料，无法自动完成该项；{rule.get('message', '需人工复核')}"
    r["suggestion"] = "请补充甲方工商信息截图或人工核验记录后再复核，当前保持人工确认。"
    return _make_finding(r, evidence="未提供外部工商核验材料", location="外部核验材料", confidence=0.55)


def _build_a1_external_finding(rule: dict[str, Any], external_checks: dict[str, Any]) -> dict[str, Any] | None:
    party_match = external_checks.get("party_a_match") or {}
    issues = party_match.get("issues") or []
    if not issues:
        return None

    severity = "block" if any(item.get("severity") == "block" for item in issues) else "warn"
    issue_lines = [
        (
            f"{item.get('field')}：合同[{item.get('contract_value') or '-'}]"
            f" vs 外部[{item.get('external_value') or '-'}]"
        )
        for item in issues
    ]
    evidence = "；".join(issue_lines[:6])
    evidence = f"{evidence}；{_format_external_context(external_checks)}"

    r = dict(rule)
    r["severity"] = severity
    if severity == "block":
        r["message"] = "外部核验发现甲方工商关键信息不一致（含信用代码/经营状态等），需阻断签署并复核。"
    else:
        r["message"] = "外部核验发现甲方工商信息存在差异，建议人工复核并补充证明材料。"
    r["suggestion"] = "核对并修订合同中的甲方名称、信用代码、法定代表人、注册地址与经营状态。"
    return _make_finding(r, evidence=evidence, location="外部核验材料", confidence=0.88 if severity == "block" else 0.8)


def _build_a2_external_finding(rule: dict[str, Any], external_checks: dict[str, Any]) -> dict[str, Any] | None:
    related = external_checks.get("related_party_check") or {}
    status = related.get("status")
    if status == "clear":
        return None

    if status == "related":
        r = dict(rule)
        r["severity"] = related.get("risk_level") or "warn"
        r["message"] = related.get("message") or "发现疑似关联关系，需提供关联关系声明。"
        r["suggestion"] = "请补充关联关系声明并完成合规审批。"
        people = related.get("matched_people") or []
        people_text = "、".join([str(x) for x in people]) if people else "未提供具体名单"
        evidence = f"命中人员：{people_text}；{_format_external_context(external_checks)}"
        return _make_finding(r, evidence=evidence, location="外部核验材料", confidence=0.84)

    r = dict(rule)
    r["message"] = related.get("message") or "缺少课题组名单，无法判断关联关系。"
    if related.get("company_personnel_provided") and not related.get("research_team_provided"):
        r["suggestion"] = "请补充项目负责人和课题组成员名单，用已取得的甲方法定代表人、股东、高管等信息进行姓名比对；只有命中时才需另行提交关联关系声明。"
    else:
        r["suggestion"] = "请补充课题组成员名单，并结合甲方法人、股东、高管等信息复核是否存在关联关系。"
    return _make_finding(r, evidence=_format_external_context(external_checks), location="外部核验材料", confidence=0.62)


def _build_a3_external_finding(rule: dict[str, Any], external_checks: dict[str, Any]) -> dict[str, Any] | None:
    military = external_checks.get("military_defense_check") or {}
    status = military.get("status")
    if status == "clear":
        return None

    if status in {"related", "suspected"}:
        r = dict(rule)
        r["severity"] = military.get("risk_level") or "warn"
        r["message"] = military.get("message") or "疑似军工/国防/涉密相关，需重点复核。"
        r["suggestion"] = "补充军工/涉密核验说明，并由项目负责人确认；同时检查封面密级标注。"
        evidence_items = []
        evidence_items.extend([str(x) for x in (military.get("evidence") or [])])
        keyword_hits = military.get("keyword_hits") or []
        if keyword_hits:
            evidence_items.append(f"关键词命中：{', '.join(keyword_hits)}")
        evidence_items.append(_format_external_context(external_checks))
        return _make_finding(
            r,
            evidence="；".join([x for x in evidence_items if x]) or "需人工复核",
            location="外部核验材料",
            confidence=0.86 if r["severity"] == "block" else 0.76,
        )

    r = dict(rule)
    r["message"] = military.get("message") or "仍需人工确认项目是否涉军工/涉密。"
    r["suggestion"] = "请项目负责人确认并检查封面密级标注。"
    return _make_finding(r, evidence=_format_external_context(external_checks), location="外部核验材料", confidence=0.6)


def _build_external_checks(
    extracted: dict[str, Any],
    full_text: str,
    company_check: dict[str, Any] | None,
) -> dict[str, Any]:
    if not company_check:
        return {
            "company_check_provided": False,
            "source": "",
            "checked_at": "",
            "evidence_files": [],
            "party_a_match": {
                "status": "not_provided",
                "contract": {
                    "name": normalize_spaces(extracted.get("party_a", {}).get("name", "")),
                    "credit_code": normalize_spaces(extracted.get("party_a", {}).get("credit_code", "")),
                    "legal_rep": normalize_spaces(extracted.get("party_a", {}).get("legal_rep", "")),
                    "registered_address": normalize_spaces(extracted.get("party_a", {}).get("address", "")),
                },
                "external": {},
                "issues": [],
            },
            "related_party_check": {
                "status": "not_provided",
                "message": "未提供外部工商核验材料，无法自动完成关联关系核验。",
            },
            "military_defense_check": {
                "status": "not_provided",
                "message": "未提供外部工商核验材料，无法自动完成军工/涉密核验。",
                "manual_confirmation_required": True,
            },
        }

    party_match = compare_party_a(extracted.get("party_a", {}) or {}, company_check)
    related_party = check_related_party(company_check)
    military_defense = check_military_defense(company_check, full_text)

    return {
        "company_check_provided": True,
        "source": company_check.get("source", ""),
        "checked_at": company_check.get("checked_at", ""),
        "evidence_files": company_check.get("evidence_files") or [],
        "party_a_match": party_match,
        "related_party_check": related_party,
        "military_defense_check": military_defense,
    }


def _format_external_context(external_checks: dict[str, Any]) -> str:
    source = external_checks.get("source") or "未知来源"
    checked_at = external_checks.get("checked_at") or "未知时间"
    evidence_files = external_checks.get("evidence_files") or []
    evidence_text = "、".join([str(x) for x in evidence_files]) if evidence_files else "无"
    return f"来源={source}，核验时间={checked_at}，证据文件={evidence_text}"


def _run_enforce_check(rule: dict[str, Any], extracted: dict[str, Any], text: str) -> dict[str, Any] | None:
    check_type = rule.get("check_type")
    if check_type in {"party_name", "basic_parties"}:
        return _check_basic_parties(rule, extracted)
    if check_type == "contacts_required":
        return _check_contacts_required(rule, extracted)
    if check_type == "contact_email_domain":
        return _check_contact_email_domain(rule, extracted)
    if check_type == "phrase_any":
        ev = _evidence_from_patterns(text, rule.get("patterns") or [])
        if ev:
            return _make_finding(rule, evidence=ev, location=_locate(text, ev), confidence=0.82)
        return None
    if check_type == "forbidden_phrase_any":
        if rule.get("id") == "B3":
            hit = _hit_institution_setup_combo(text)
            if hit:
                return _make_finding(rule, evidence=hit, location=_locate(text, hit), confidence=0.84)
            return None
        ev = _evidence_from_patterns(text, rule.get("patterns") or [])
        if ev:
            return _make_finding(rule, evidence=ev, location=_locate(text, ev), confidence=0.86)
        return None
    if check_type == "required_phrase":
        ev = _evidence_from_patterns(text, rule.get("patterns") or [])
        if not ev:
            return _make_finding(rule, evidence="未检出必需条款", location="全文", confidence=0.78)
        return None
    if check_type == "bank_account":
        return _check_bank_account(rule, extracted)
    if check_type == "payment_first_installment":
        return _check_payment_first_installment(rule, extracted)
    if check_type == "performance_budget":
        return _check_performance_budget(rule, text)
    if check_type == "ip_ownership":
        return _check_ip_ownership(rule, extracted)
    if check_type == "shared_ip_distribution":
        return _check_shared_ip_distribution(rule, extracted)
    if check_type == "confidentiality_term":
        return _check_confidentiality_term(rule, extracted)
    if check_type == "date_term":
        return _check_date_term(rule, text)
    if check_type == "liability_cap":
        return _check_liability(rule, extracted)
    if check_type == "arbitration_name":
        return _check_arbitration(rule, extracted)
    if check_type == "blanks":
        return _check_blanks(rule, extracted)
    if check_type == "attachment_presence":
        return _check_attachment_presence(rule, extracted)
    if check_type == "related_agreement_presence":
        return _check_related_agreement_presence(rule, extracted)
    return None


def _check_basic_parties(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    project_name = normalize_spaces(extracted.get("project_name", ""))
    party_a = normalize_spaces(extracted.get("party_a", {}).get("name", ""))
    party_b = normalize_spaces(extracted.get("party_b", {}).get("name", ""))
    if not party_a:
        r = dict(rule)
        r["severity"] = "warn"
        return _make_finding(r, evidence="未识别甲方/委托方名称", location="合同基础信息", confidence=0.82)
    if "中山大学" not in party_b:
        return _make_finding(rule, evidence=f"乙方={party_b or '未识别'}", location="乙方信息", confidence=0.95)
    subunit_words = ["学院", "研究院", "实验室", "中心", "系"]
    if any(w in party_b for w in subunit_words) and party_b != "中山大学":
        r = dict(rule)
        r["severity"] = "warn"
        return _make_finding(r, evidence=f"乙方={party_b}", location="乙方信息", confidence=0.88)
    if not project_name:
        r = dict(rule)
        r["severity"] = "warn"
        return _make_finding(r, evidence="未识别项目名称或标题项目名疑似留空", location="合同基础信息/标题", confidence=0.8)
    return None


def _check_contacts_required(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    text = extracted.get("full_text", "")
    missing: list[str] = []
    groups = {
        "联系人": ["联系人", "项目联系人"],
        "通讯地址": ["通讯地址", "地址"],
        "电话": ["电话", "联系电话", "手机"],
        "邮编": ["邮编"],
        "邮箱/电邮": ["邮箱", "电邮", "E-mail", "Email", "电子邮箱"],
    }
    for label, variants in groups.items():
        if not any(v in text for v in variants):
            missing.append(label)
    if missing:
        r = dict(rule)
        r["severity"] = "warn"
        return _make_finding(r, evidence=f"缺少字段：{', '.join(missing)}", location="联系人条款", confidence=0.82)
    return None


def _check_contact_email_domain(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    text = extracted.get("full_text", "")
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", text)
    sysu_emails = [email for email in emails if email.lower().endswith(("sysu.edu.cn", "mail.sysu.edu.cn"))]
    if sysu_emails:
        return None
    if emails:
        return _make_finding(rule, evidence="; ".join(emails[:5]), location="联系人条款", confidence=0.76)
    return _make_finding(rule, evidence="未识别联系人邮箱", location="联系人条款", confidence=0.72)


def _check_bank_account(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    bank = extracted.get("bank_account", {})
    expected = {"name": "中山大学", "account": "44050143004609000001", "bank": "中国建设银行广州中山大学支行"}
    if bank.get("account") and bank.get("account") != expected["account"]:
        r = dict(rule)
        r["severity"] = "block"
        return _make_finding(r, evidence=f"账号={bank.get('account')}", location="账户条款", confidence=0.95)
    if not any(bank.get(k) for k in ("name", "account", "bank")):
        r = dict(rule)
        r["severity"] = "warn"
        missing_refs = extracted.get("missing_referenced_attachments", [])
        if missing_refs:
            evidence = f"未识别中山大学收款账户；合同引用{', '.join(missing_refs)}但正文未见对应附件"
        else:
            evidence = "未识别中山大学收款账户"
        return _make_finding(r, evidence=evidence, location="账户/付款条款", confidence=0.8)
    if not bank.get("name") or expected["name"] not in bank.get("name", ""):
        r = dict(rule)
        r["severity"] = "warn"
        return _make_finding(r, evidence=f"户名={bank.get('name') or '缺失'}", location="账户条款", confidence=0.86)
    if not bank.get("bank") or expected["bank"] not in bank.get("bank", ""):
        return _make_finding(rule, evidence=f"开户行={bank.get('bank') or '缺失'}", location="账户条款", confidence=0.86)
    return None


def _check_payment_first_installment(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    raw_terms = extracted.get("payment_terms", [])
    terms = "\n".join(raw_terms)
    hard_bad = ["提交所有项目成果后支付全款", "验收合格后支付全部", "交付全部成果后付款", "项目完成后一次性支付"]
    for p in hard_bad:
        if p in terms:
            r = dict(rule)
            r["severity"] = "block"
            return _make_finding(r, evidence=p, location="付款条款", confidence=0.93)
    concrete_terms = extracted.get("concrete_payment_terms", [])
    if not concrete_terms:
        r = dict(rule)
        r["severity"] = "warn"
        missing_refs = extracted.get("missing_referenced_attachments", [])
        if missing_refs:
            evidence = f"合同称付款计划在{', '.join(missing_refs)}中，但当前文档未见具体付款节点"
        else:
            evidence = "未识别具体付款节点" if terms else "未识别付款计划"
        return _make_finding(r, evidence=evidence, location="付款条款", confidence=0.74)
    concrete_text = "\n".join(concrete_terms)
    if any(k in concrete_text for k in ["合同生效后", "签订后", "首付款", "预付款"]):
        return None
    r = dict(rule)
    r["severity"] = "warn"
    return _make_finding(r, evidence=concrete_text[:180], location="付款条款", confidence=0.68)


def _check_performance_budget(rule: dict[str, Any], text: str) -> dict[str, Any] | None:
    if "绩效" not in text:
        evidence = "未检索到“绩效”描述"
        if "工作任务书" in text and "经费构成" in text:
            evidence = "主合同称经费构成由工作任务书/SOW约定，但当前文档未见绩效说明"
        return _make_finding(rule, evidence=evidence, location="经费条款", confidence=0.85)
    perf_lines = "\n".join([ln for ln in text.splitlines() if "绩效" in ln][:5])
    if not re.search(r"(不超过|最多|上限).{0,4}70%|70%", perf_lines):
        return _make_finding(rule, evidence=perf_lines or "绩效条款缺70%说明", location="经费条款", confidence=0.82)
    return None


def _check_ip_ownership(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    ip_text = "\n".join(extracted.get("ip_clauses", []))
    if not ip_text:
        return _make_finding(rule, evidence="未发现知识产权归属条款", location="知识产权条款", confidence=0.8)
    details = _describe_ip_arrangements(ip_text)
    if details["generated_ip_ownership"] or details["background_ip_use_arrangement"]:
        r = dict(rule)
        r["message"] = _build_ip_message(details)
        r["suggestion"] = (
            "优先协商项目产生的开发成果/知识产权由双方共有并明确权利、收益比例；"
            "如坚持归甲方单方所有，应补交《项目承诺书1（一般知识产权相关条款）》；"
            "同时复核乙方背景知识产权使用范围、期限、对象（含关联公司/第三方）及费用安排。"
        )
        evidence = _join_nonempty(
            [
                details["generated_ip_ownership"],
                details["background_ip_ownership"],
                details["background_ip_use_arrangement"],
            ],
            sep=" ",
        )
        return _make_finding(
            r,
            evidence=evidence[:520],
            location="知识产权条款",
            confidence=0.92 if details["generated_ip_ownership"] else 0.86,
            details=details,
        )
    risky = ["归甲方所有", "甲方单方所有", "全部归甲方所有", "均归甲方所有", "甲方及其关联公司可以使用"]
    for ln in ip_text.splitlines():
        if any(k in ln for k in risky):
            return _make_finding(rule, evidence=ln[:220], location="知识产权条款", confidence=0.9)
    if "双方共有" in ip_text and not re.search(r"比例|份额|收益分配|各方", ip_text):
        return _make_finding(rule, evidence=ip_text[:160], location="知识产权条款", confidence=0.84)
    return None


def _check_shared_ip_distribution(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    ip_text = "\n".join(extracted.get("ip_clauses", []))
    if "双方共有" not in ip_text:
        return None
    if re.search(r"比例|份额|收益分配|权利比例|各方", ip_text):
        return None
    return _make_finding(rule, evidence=ip_text[:180], location="知识产权条款", confidence=0.84)


def _check_confidentiality_term(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    text = "\n".join(extracted.get("confidentiality_clauses", []))
    if not text:
        full_text = extracted.get("full_text", "")
        lines = [ln for ln in full_text.splitlines() if ("保密" in ln or "NDA" in ln.upper())]
        text = "\n".join(lines[:12])
    if not text:
        return None
    strict_unlimited = re.search(r"(?:保密期限|保密义务(?:期限)?)[^\n。；]{0,30}(无限期|无期限|永久|长期|长期有效|持续有效)", text)
    if strict_unlimited:
        r = dict(rule)
        r["severity"] = "block"
        return _make_finding(r, evidence=strict_unlimited.group(0), location="保密条款", confidence=0.92)
    year_hits = re.findall(r"(?:保密期限|保密义务(?:期限)?)[^\n。；]{0,20}?(\d+)\s*年", text)
    if year_hits and max(int(x) for x in year_hits) > 5:
        r = dict(rule)
        r["severity"] = "block"
        return _make_finding(r, evidence=text[:160], location="保密条款", confidence=0.9)
    if "保密" in text and not re.search(r"保密[^\n。；]{0,20}(\d+\s*年|至|截止|期限)", text):
        r = dict(rule)
        r["severity"] = "warn"
        return _make_finding(r, evidence=text[:160], location="保密条款", confidence=0.78)
    return None


def _check_date_term(rule: dict[str, Any], text: str) -> dict[str, Any] | None:
    term_lines = [
        ln for ln in text.splitlines()
        if any(k in ln for k in ["有效期限", "合同期限", "协议期限", "履行期限", "起止日期", "工作计划"])
    ]
    term_text = "\n".join(term_lines)
    duration_hits = re.findall(r"(?:有效期限|合同期限|协议期限|履行期限|合同有效期)\s*[:：为共约 ]{0,4}(?<!\d)(\d{1,2})\s*年(?!\d)", term_text)
    if duration_hits and max(int(x) for x in duration_hits) > 5:
        return _make_finding(rule, evidence=f"期限{max(int(x) for x in duration_hits)}年", location="期限条款", confidence=0.84)
    starts = re.findall(r"(20\d{2})[年\-/](\d{1,2})[月\-/](\d{1,2})", term_text)
    today = date.today()
    for y, m, d in starts:
        try:
            dt = date(int(y), int(m), int(d))
            if dt < today and any(k in term_text for k in ["合同期限", "有效期限", "起始", "开始"]):
                return _make_finding(rule, evidence=f"起始日期={dt.isoformat()}", location="期限条款", confidence=0.7)
        except ValueError:
            continue
    return None


def _check_liability(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    text = "\n".join(extracted.get("liability_clauses", []))
    if not text:
        return None
    if any(k in text for k in ["无限责任", "全部损失", "不设上限"]):
        r = dict(rule)
        r["severity"] = "block"
        return _make_finding(r, evidence=text[:180], location="违约责任条款", confidence=0.91)
    if "超过合同总金额" in text:
        r = dict(rule)
        r["severity"] = "block"
        return _make_finding(r, evidence=text[:180], location="违约责任条款", confidence=0.9)
    if "超过甲方已付金额" in text and "不超过合同总金额" not in text:
        return _make_finding(rule, evidence=text[:180], location="违约责任条款", confidence=0.78)
    return None


def _check_arbitration(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    text = extracted.get("dispute_resolution", "")
    if not text:
        return None
    if re.search(r"[\u4e00-\u9fa5]+市仲裁委员会", text):
        return _make_finding(rule, evidence=text[:160], location="争议解决条款", confidence=0.88)
    if "法院" in text and "仲裁" not in text:
        r = dict(rule)
        r["severity"] = "info"
        r["message"] = "争议解决使用法院管辖，按要求可接受但建议人工确认"
        return _make_finding(r, evidence=text[:160], location="争议解决条款", confidence=0.7)
    return None


def _check_blanks(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    blanks = extracted.get("blanks", [])
    if not blanks:
        return None
    first = blanks[0]
    text = first.get("text", "")
    r = dict(rule)
    if any(k in text for k in ["签名", "日期", "盖章", "传真"]):
        r["severity"] = "info"
    return _make_finding(r, evidence=text, location=f"行{first.get('line', '-')}", confidence=0.85)


def _check_attachment_presence(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    patterns = rule.get("patterns") or []
    text = extracted.get("full_text", "")
    if rule.get("id") == "D2":
        ip_text = "\n".join(extracted.get("ip_clauses", []))
        owned_by_party_a = any(k in ip_text for k in ["归甲方所有", "甲方单方所有", "全部归甲方所有", "均归甲方所有"])
        if not owned_by_party_a:
            return None
        if any(p in text for p in patterns):
            return None
        return _make_finding(rule, evidence="知识产权归甲方所有，但未见项目承诺书1", location="知识产权条款", confidence=0.82)
    if any(p in text for p in patterns):
        return _make_finding(rule, evidence=_evidence_from_patterns(text, patterns), location="附件/正文", confidence=0.75)
    return None


def _check_related_agreement_presence(rule: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any] | None:
    text = extracted.get("full_text", "")
    patterns = rule.get("patterns") or []
    for ln in text.splitlines():
        if not any(p in ln for p in patterns):
            continue
        if "已经于" in ln or "是指" in ln:
            continue
        if any(k in ln for k in ["附件", "作为附件", "需签署", "需要签署", "另行签署", "另行签订", "相关廉政协议", "相关保密协议", "相关安全协议"]):
            return _make_finding(rule, evidence=ln[:180], location="协议/附件条款", confidence=0.75)
    return None


def _map_decision(findings: list[dict[str, Any]]) -> dict[str, Any]:
    if any(f.get("severity") == "block" for f in findings):
        return {"decision": "存在重大问题，需修改/补充", "confidence": 0.9}
    if findings:
        return {"decision": "基本可审，建议人工复核", "confidence": 0.72}
    return {"decision": "未发现形式化问题", "confidence": 0.95}


def _build_summary_stats(
    findings: list[dict[str, Any]],
    not_checked_items: list[dict[str, Any]],
    rule_results: list[dict[str, Any]],
) -> dict[str, Any]:
    enforce_items = [f for f in findings if f.get("scope") == "enforce"]
    enforce_risks = [f for f in enforce_items if f.get("severity") in {"block", "warn"}]
    review_items = [f for f in findings if f.get("scope") == "review"]
    info_items = [f for f in findings if f.get("severity") == "info"]

    return {
        "findings_total": len(findings),
        "risk_total": len(enforce_risks),
        "enforce_total": len(enforce_items),
        "review_total": len(review_items),
        "info_total": len(info_items),
        "not_checked_total": len(not_checked_items),
        "rules_total": len(rule_results),
        "rules_hit_total": sum(1 for item in rule_results if item.get("status") == "hit"),
        "rules_pass_total": sum(1 for item in rule_results if item.get("status") == "pass"),
        "rules_not_checked_total": sum(1 for item in rule_results if item.get("status") == "not_checked"),
        "by_scope": _count_values(findings, "scope"),
        "by_severity": _count_values(findings, "severity"),
        "risk_rule_ids": [str(f.get("rule_id")) for f in enforce_risks],
        "review_rule_ids": [str(f.get("rule_id")) for f in review_items],
        "info_rule_ids": [str(f.get("rule_id")) for f in info_items],
    }


def _count_values(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _evidence_from_patterns(text: str, patterns: list[str]) -> str:
    for p in patterns:
        if not p:
            continue
        for ln in text.splitlines():
            if p in ln:
                return ln[:240]
        if p in text:
            return p
    return ""


def _locate(text: str, evidence: str) -> str:
    if not evidence:
        return "全文"
    lines = text.splitlines()
    for idx, ln in enumerate(lines, start=1):
        if evidence in ln:
            return f"第{idx}行"
    return "全文"


def _hit_institution_setup_combo(text: str) -> str:
    verbs = ["联合成立", "共同成立", "设立", "共建", "联合建设"]
    nouns = ["平台", "实验室", "中心", "研究院", "基地"]
    for ln in text.splitlines():
        if any(v in ln for v in verbs) and any(n in ln for n in nouns):
            return ln[:160]
    return ""


def _describe_ip_arrangements(ip_text: str) -> dict[str, Any]:
    generated = _find_ip_sentence(
        ip_text,
        must_any=["归甲方所有", "甲方单方所有", "全部归甲方所有", "均归甲方所有"],
        context_any=["本合同下产生", "协议工作中产生", "开发成果", "知识产权"],
    )
    background_ownership = _find_ip_sentence(
        ip_text,
        must_any=["各自所有", "归各自所有", "各自享有"],
        context_any=["背景知识产权"],
    )
    background_use = _find_ip_sentence(
        ip_text,
        must_any=["实施", "使用", "委托第三方", "另行付费", "费用"],
        context_any=["背景知识产权"],
    )

    risk_focus: list[str] = []
    if generated:
        risk_focus.append("项目产生的开发成果/知识产权约定归甲方单方所有")
    if background_ownership:
        risk_focus.append("背景知识产权所有权约定归各自所有，不应表述为所有权转移")
    if background_use:
        risk_focus.append("乙方背景知识产权存在供甲方及其关联公司使用/实施或委托第三方实施的安排，需复核范围、对象、期限和费用")

    return {
        "generated_ip_ownership": generated,
        "background_ip_ownership": background_ownership,
        "background_ip_use_arrangement": background_use,
        "risk_focus": risk_focus,
    }


def _find_ip_sentence(ip_text: str, must_any: list[str], context_any: list[str]) -> str:
    for segment in _split_cn_sentences(ip_text):
        if any(ctx in segment for ctx in context_any) and any(token in segment for token in must_any):
            return segment[:260]
    return ""


def _split_cn_sentences(text: str) -> list[str]:
    segments = re.split(r"(?<=[。；;])\s*|\n+", text)
    return [normalize_spaces(segment) for segment in segments if normalize_spaces(segment)]


def _build_ip_message(details: dict[str, Any]) -> str:
    generated = details.get("generated_ip_ownership")
    background_ownership = details.get("background_ip_ownership")
    background_use = details.get("background_ip_use_arrangement")

    parts: list[str] = []
    if generated:
        parts.append("项目产生的开发成果/知识产权被约定归甲方所有，触发技术开发合同知识产权原则上双方共有的复核要求。")
    if background_ownership:
        parts.append("背景知识产权所有权条款约定为双方各自所有，该部分不是所有权转移。")
    if background_use:
        parts.append("但背景知识产权另有使用/实施安排，涉及甲方及其关联公司或第三方实施、费用内含/不另付费等内容，需单独复核。")
    return "".join(parts) or "知识产权归属条款存在风险或信息不足"


def _join_nonempty(values: list[str], sep: str) -> str:
    return sep.join([value for value in values if value])


def _make_finding(
    rule: dict[str, Any],
    evidence: str,
    location: str,
    confidence: float,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finding = {
        "rule_id": rule.get("id"),
        "section": rule.get("section"),
        "severity": rule.get("severity", "warn"),
        "scope": rule.get("scope", "enforce"),
        "title": rule.get("title"),
        "evidence": evidence or "未提取到直接证据",
        "location": location or "全文",
        "message": rule.get("message", "请人工复核"),
        "suggestion": rule.get("suggestion", "请根据审核要点补充或修订"),
        "confidence": round(confidence, 2),
    }
    if details:
        finding["details"] = details
    return finding


def _make_rule_result(rule: dict[str, Any], status: str, finding: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "rule_id": rule.get("id"),
        "section": rule.get("section"),
        "scope": rule.get("scope"),
        "severity": (finding or rule).get("severity", rule.get("severity", "")),
        "title": rule.get("title"),
        "status": status,
    }
