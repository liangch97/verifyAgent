from __future__ import annotations

import re
from typing import Any


_GOOD_COMPANY_STATUS = {"存续", "在业", "正常", "开业", "在营", "在册"}
_MILITARY_KEYWORDS = ["军工", "国防", "兵器", "军方", "军事", "涉密", "保密资质", "武器装备"]


def compare_party_a(contract_party_a: dict[str, Any], company_check: dict[str, Any]) -> dict[str, Any]:
    external = (company_check or {}).get("party_a", {}) or {}
    contract = contract_party_a or {}

    issues: list[dict[str, str]] = []
    name_match = _name_equal(contract.get("name"), external.get("name"))
    credit_match = _field_equal(contract.get("credit_code"), external.get("credit_code"))
    legal_rep_match = _field_equal(contract.get("legal_rep"), external.get("legal_rep"))
    address_match = _address_equal(contract.get("address"), external.get("registered_address"))

    if name_match is False:
        severity = _name_mismatch_severity(contract.get("name"), external.get("name"))
        issues.append(
            _issue("name", severity, "合同甲方名称与外部核验不一致", contract.get("name"), external.get("name"))
        )

    if credit_match is False:
        issues.append(
            _issue(
                "credit_code",
                "block",
                "统一社会信用代码不一致",
                contract.get("credit_code"),
                external.get("credit_code"),
            )
        )

    if legal_rep_match is False:
        issues.append(
            _issue("legal_rep", "warn", "法定代表人与外部核验不一致", contract.get("legal_rep"), external.get("legal_rep"))
        )

    if address_match is False:
        issues.append(
            _issue(
                "registered_address",
                "warn",
                "注册地址/住所地址存在明显差异",
                contract.get("address"),
                external.get("registered_address"),
            )
        )

    status = _clean_text(external.get("company_status"))
    status_ok = None
    if status:
        status_ok = any(ok in status for ok in _GOOD_COMPANY_STATUS)
        if not status_ok:
            sev = "block" if any(k in status for k in ["吊销", "注销", "异常", "停业", "清算", "迁出"]) else "warn"
            issues.append(_issue("company_status", sev, "企业经营状态异常", "", status))

    return {
        "status": "mismatch" if issues else "matched",
        "contract": {
            "name": _clean_text(contract.get("name")),
            "credit_code": _clean_text(contract.get("credit_code")),
            "legal_rep": _clean_text(contract.get("legal_rep")),
            "registered_address": _clean_text(contract.get("address")),
        },
        "external": {
            "name": _clean_text(external.get("name")),
            "credit_code": _clean_text(external.get("credit_code")),
            "legal_rep": _clean_text(external.get("legal_rep")),
            "registered_address": _clean_text(external.get("registered_address")),
            "company_status": status,
            "company_type": _clean_text(external.get("company_type")),
            "business_scope": _clean_text(external.get("business_scope")),
        },
        "name_match": name_match,
        "credit_code_match": credit_match,
        "legal_rep_match": legal_rep_match,
        "address_match": address_match,
        "status_ok": status_ok,
        "issues": issues,
    }


def check_related_party(company_check: dict[str, Any]) -> dict[str, Any]:
    payload = company_check or {}
    party_a = payload.get("party_a", {}) or {}
    research_team = payload.get("research_team") or []
    matches = party_a.get("related_person_matches") or []
    related_flag = party_a.get("related_to_research_team")
    provided_research_team = bool(research_team)
    company_personnel = []
    company_personnel.extend(party_a.get("shareholders") or [])
    company_personnel.extend(party_a.get("directors") or [])
    company_personnel.extend(party_a.get("executives") or [])
    company_personnel_provided = bool(company_personnel or party_a.get("legal_rep"))

    if related_flag is True or bool(matches):
        return {
            "status": "related",
            "risk_level": "warn",
            "requires_statement": True,
            "matched_people": [str(x) for x in matches],
            "research_team_provided": provided_research_team,
            "company_personnel_provided": company_personnel_provided,
            "message": "发现甲方/法人/股东/高管与课题组疑似关联，需提供关联关系声明。",
        }

    if related_flag is False and provided_research_team:
        return {
            "status": "clear",
            "risk_level": "pass",
            "requires_statement": False,
            "matched_people": [],
            "research_team_provided": True,
            "company_personnel_provided": company_personnel_provided,
            "message": "未发现关联关系。",
        }

    if company_personnel_provided and not provided_research_team:
        message = "已取得甲方法定代表人/股东/高管等可见信息，但缺少课题组成员名单，无法完成关联关系比对。"
    else:
        message = "缺少课题组名单或外部核验信息不足，无法判断关联关系。"

    return {
        "status": "insufficient_info",
        "risk_level": "review",
        "requires_statement": False,
        "matched_people": [str(x) for x in matches],
        "research_team_provided": provided_research_team,
        "company_personnel_provided": company_personnel_provided,
        "message": message,
    }


def check_military_defense(company_check: dict[str, Any], contract_text: str) -> dict[str, Any]:
    payload = company_check or {}
    party_a = payload.get("party_a", {}) or {}
    explicit = party_a.get("is_military_or_defense_related")
    external_evidence = [str(x) for x in (party_a.get("military_or_defense_evidence") or [])]

    blob = "\n".join(
        [
            _clean_text(party_a.get("name")),
            _clean_text(party_a.get("company_type")),
            _clean_text(party_a.get("business_scope")),
        ]
    )
    keyword_hits = [kw for kw in _MILITARY_KEYWORDS if kw in blob]
    safe_contract = "民用用途" in (contract_text or "") and (
        "不涉及军事单位" in (contract_text or "") or "不涉及国家秘密" in (contract_text or "")
    )

    if explicit is True:
        return {
            "status": "related",
            "risk_level": "block",
            "manual_confirmation_required": True,
            "keyword_hits": keyword_hits,
            "evidence": external_evidence,
            "message": "外部核验显示甲方与军工/国防/涉密相关，需重点审查。",
        }

    if keyword_hits:
        return {
            "status": "suspected",
            "risk_level": "warn",
            "manual_confirmation_required": True,
            "keyword_hits": keyword_hits,
            "evidence": external_evidence,
            "message": "外部企业信息命中军工/国防/涉密关键词，建议人工复核。",
        }

    if explicit is False and safe_contract:
        return {
            "status": "clear",
            "risk_level": "pass",
            "manual_confirmation_required": True,
            "keyword_hits": [],
            "evidence": external_evidence,
            "message": "外部核验未见军工/涉密属性，且合同含民用/非涉密表述。",
        }

    return {
        "status": "manual_review",
        "risk_level": "review",
        "manual_confirmation_required": True,
        "keyword_hits": [],
        "evidence": external_evidence,
        "message": "仍需项目负责人确认并检查封面密级标注。",
    }


def _name_equal(contract_name: Any, external_name: Any) -> bool | None:
    c = _clean_compact(contract_name)
    e = _clean_compact(external_name)
    if not c or not e:
        return None
    return c == e


def _field_equal(contract_value: Any, external_value: Any) -> bool | None:
    c = _clean_compact(contract_value)
    e = _clean_compact(external_value)
    if not c or not e:
        return None
    return c == e


def _address_equal(contract_address: Any, external_address: Any) -> bool | None:
    c = _clean_compact(contract_address)
    e = _clean_compact(external_address)
    if not c or not e:
        return None
    if c == e or c in e or e in c:
        return True
    return c[:6] == e[:6]


def _name_mismatch_severity(contract_name: Any, external_name: Any) -> str:
    c = _clean_compact(contract_name)
    e = _clean_compact(external_name)
    if not c or not e:
        return "warn"
    if c in e or e in c:
        return "warn"
    overlap = len(set(c) & set(e))
    if overlap >= max(2, int(min(len(c), len(e)) * 0.6)):
        return "warn"
    return "block"


def _issue(field: str, severity: str, message: str, contract_value: Any, external_value: Any) -> dict[str, str]:
    return {
        "field": field,
        "severity": severity,
        "message": message,
        "contract_value": _clean_text(contract_value),
        "external_value": _clean_text(external_value),
    }


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_compact(value: Any) -> str:
    text = _clean_text(value)
    return re.sub(r"[\s\-_,，。；;:：()（）\[\]【】]", "", text)
