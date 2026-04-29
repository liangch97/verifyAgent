from __future__ import annotations

import re
from typing import Any

from .utils import find_first, normalize_spaces


HEADING_RE = re.compile(
    r"^("
    r"第[一二三四五六七八九十百零〇\d]+[条章节部分]"
    r"|[0-9]+(?:\.[0-9]+)*"
    r"|第[一二三四五六七八九十]+部分"
    r"|[一二三四五六七八九十]+[、.]"
    r"|（[一二三四五六七八九十]+）"
    r"|附件"
    r")"
)

# Party-role aliases: when 甲方/乙方 are not used directly, fall back to these.
# Mapping points to the canonical role ("甲" or "乙") indicating which extraction slot to fill.
_PARTY_ROLE_ALIASES: dict[str, str] = {
    "甲方": "甲",
    "委托方": "甲",
    "项目甲方": "甲",
    "需求方": "甲",
    "转让方": "甲",
    "采购方": "甲",
    "乙方": "乙",
    "项目乙方": "乙",
    "受托方": "乙",
    "研究方": "乙",
    "服务方": "乙",
    "受让方": "乙",
    "合作方": "乙",
    "供方": "乙",
}


def extract_contract(loaded: dict[str, Any]) -> dict[str, Any]:
    blocks = loaded.get("ordered_blocks", [])
    lines = [normalize_spaces(b.get("text", "")) for b in blocks if normalize_spaces(b.get("text", ""))]
    text = "\n".join(lines)

    title = _extract_title(lines)
    contract_no = find_first([
        r"合同编号[：: ]*([A-Za-z0-9\-_/]+)",
        r"协议编号[：: ]*([A-Za-z0-9\-_/]+)",
    ], text)
    sign_place = find_first([r"签订地点[：: ]*([^\n]+)", r"签署地点[：: ]*([^\n]+)"], text)

    party_a_name = _extract_party_name(text, "甲")
    party_b_name = _extract_party_name(text, "乙")

    project_name = _extract_project_name(lines, text, title)
    contract_type = _infer_contract_type(text, title)

    amount = _extract_amount(text)

    payment_terms = _extract_lines_by_keywords(lines, ["付款", "支付", "首付款", "验收", "成果提交", "款项"])
    concrete_payment_terms = _filter_concrete_payment_terms(payment_terms)
    bank_account = {
        "name": find_first([r"户名[：: ]*([^\n]+)"], text),
        "account": find_first([r"账号[：: ]*([0-9]{8,})"], text),
        "bank": find_first([r"开户行[：: ]*([^\n]+)"], text),
    }

    contacts = _extract_contacts(lines)
    sections = _split_sections(lines)
    attachments = [ln for ln in lines if ln.startswith("附件") or "附件" in ln[:8]]
    missing_referenced_attachments = _detect_missing_referenced_attachments(lines, attachments)
    dates = _extract_dates(text)

    ip_clauses = _extract_lines_by_keywords(lines, ["知识产权", "专利", "著作权", "版权", "商业秘密", "背景知识产权"])
    confidentiality_clauses = _extract_lines_by_keywords(lines, ["保密", "秘密", "机密"])
    liability_clauses = _extract_lines_by_keywords(lines, ["违约", "赔偿", "损失", "责任", "律师费", "调查费"])

    dispute_resolution = "\n".join(_extract_lines_by_keywords(lines, ["争议", "仲裁", "法院", "管辖"]))
    blanks = _extract_blanks(lines)

    return {
        "source_file": loaded.get("source_file", ""),
        "title": title,
        "contract_no": contract_no,
        "sign_place": sign_place,
        "party_a": {
            "name": party_a_name,
            "address": find_first([r"甲方[^\n]{0,8}地址[：: ]*([^\n]+)"], text),
            "legal_rep": find_first([r"甲方[^\n]{0,8}(?:法定代表人|法人)[：: ]*([^\n]+)"], text),
            "credit_code": find_first([r"甲方[^\n]{0,12}(?:统一社会信用代码|信用代码)[：: ]*([A-Za-z0-9]{10,30})"], text),
        },
        "party_b": {
            "name": party_b_name,
            "address": find_first([r"乙方[^\n]{0,8}地址[：: ]*([^\n]+)"], text),
        },
        "project_name": project_name,
        "contract_type": contract_type,
        "amount": amount,
        "payment_terms": payment_terms,
        "concrete_payment_terms": concrete_payment_terms,
        "bank_account": bank_account,
        "contacts": contacts,
        "sections": sections,
        "attachments": attachments,
        "missing_referenced_attachments": missing_referenced_attachments,
        "dates": dates,
        "ip_clauses": ip_clauses,
        "confidentiality_clauses": confidentiality_clauses,
        "liability_clauses": liability_clauses,
        "dispute_resolution": dispute_resolution,
        "blanks": blanks,
        "raw_text_excerpt": text[:4000],
        "comments": loaded.get("comments", []),
        "highlights": loaded.get("highlights", []),
        "full_text": text,
        "template_match": _detect_template_match_safe(text, loaded.get("source_file", "")),
    }


def _detect_template_match_safe(text: str, source_path: str) -> dict:
    try:
        from .template_matcher import detect_template_match
    except Exception:
        try:
            from template_matcher import detect_template_match  # type: ignore
        except Exception:
            return {"matched": False, "error": "template_matcher unavailable"}
    try:
        return detect_template_match(text, contract_path=source_path)
    except Exception as e:
        return {"matched": False, "error": str(e)}


def _extract_title(lines: list[str]) -> str:
    for ln in lines[:20]:
        if len(ln) >= 6 and any(k in ln for k in ["合同", "协议", "技术", "合作"]):
            return ln
    return lines[0] if lines else ""


def _infer_contract_type(text: str, title: str) -> str:
    blob = f"{title}\n{text[:800]}"
    if "技术开发合同" in blob:
        return "技术开发合同"
    if "研究开发" in blob:
        return "技术开发合同"
    if "技术合作" in blob:
        return "技术合作协议"
    if "合作协议" in blob and "技术" in blob:
        return "技术合作协议"
    if "技术服务" in blob:
        return "技术服务合同"
    if "横向" in blob:
        return "横向科研合同"
    return "未识别"


def _extract_project_name(lines: list[str], text: str, title: str) -> str:
    direct = find_first([r"项目名称[：: ]*([^\n]+)", r"合作项目[：: ]*([^\n]+)"], text)
    if direct:
        return direct.strip("【】[] ")
    for candidate in [title, *lines[:5]]:
        m = re.search(r"[“\"']([^“”\"']+)[”\"']\s*(?:合作)?(?:协议|合同)", candidate)
        if m and m.group(1).strip():
            return m.group(1).strip()
        if re.search(r"[“\"']\s*[”\"']\s*(?:合作)?(?:协议|合同)", candidate):
            return ""
    return ""


def _extract_amount(text: str) -> str:
    patterns = [
        r"(?:合同总金额|合同金额|项目经费|经费总额)[^。\n；]{0,12}?(人民币[^。\n；]{0,60})",
        r"(?:合同总金额|合同金额|项目经费|经费总额)[^。\n；]{0,12}?([0-9][0-9,，.]*\s*(?:万元|元))",
        r"人民币[（(]?[大写小写]*[）)]?[：: ]*([^。\n；]{0,60}(?:万元|元))",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = match.group(1).strip()
            context = match.group(0)
            if "未支付" in context or "另行付费" in context:
                continue
            return value
    return ""


def _filter_concrete_payment_terms(payment_terms: list[str]) -> list[str]:
    concrete: list[str] = []
    for ln in payment_terms:
        if "工作任务书" in ln and "付款计划" in ln:
            continue
        if "支付取决于双方友好协商" in ln:
            continue
        if "未支付部分" in ln and "扣除" in ln:
            continue
        has_payment_word = any(k in ln for k in ["支付", "付款", "拨付"])
        has_node_detail = any(k in ln for k in ["首付款", "预付款", "合同生效后", "签订后", "日内", "工作日", "%", "元", "万元"])
        if has_payment_word and has_node_detail:
            concrete.append(ln)
    return concrete


def _detect_missing_referenced_attachments(lines: list[str], attachments: list[str]) -> list[str]:
    text = "\n".join(lines)
    missing: list[str] = []
    has_attachment_body = any(re.search(r"^附件\s*\d+", ln) for ln in attachments)
    if ("工作任务书见附件" in text or "附件1提供了工作任务书" in text) and not has_attachment_body:
        missing.append("工作任务书/SOW")
    return missing


def _split_sections(lines: list[str]) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current = {"heading": "前言", "content": ""}
    for ln in lines:
        if HEADING_RE.match(ln):
            if current["content"].strip():
                sections.append(current)
            current = {"heading": ln, "content": ""}
        else:
            current["content"] += ("\n" + ln)
    if current["content"].strip() or current["heading"] != "前言":
        sections.append(current)
    return sections


def _extract_dates(text: str) -> list[str]:
    patterns = [
        r"\d{4}年\d{1,2}月\d{1,2}日",
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{4}/\d{1,2}/\d{1,2}",
    ]
    hits: list[str] = []
    for p in patterns:
        hits.extend(re.findall(p, text))
    return sorted(set(hits))


def _extract_lines_by_keywords(lines: list[str], keywords: list[str]) -> list[str]:
    out: list[str] = []
    for ln in lines:
        if any(k in ln for k in keywords):
            out.append(ln)
    return out


def _extract_contacts(lines: list[str]) -> list[dict[str, str]]:
    contacts: list[dict[str, str]] = []
    for idx, ln in enumerate(lines):
        if "联系人" in ln:
            email = ""
            phone = ""
            address = ""
            postcode = ""
            snippet = "\n".join(lines[idx: min(idx + 8, len(lines))])
            m_email = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)", snippet)
            if m_email:
                email = m_email.group(1)
            m_phone = re.search(r"(1[3-9]\d{9}|0\d{2,3}-?\d{7,8})", snippet)
            if m_phone:
                phone = m_phone.group(1)
            m_post = re.search(r"(\d{6})", snippet)
            if m_post:
                postcode = m_post.group(1)
            m_addr = re.search(r"(?:通讯地址|地址)[：: ]*([^\n]+)", snippet)
            if m_addr:
                address = m_addr.group(1).strip()
            contacts.append({
                "role": ln,
                "name": _extract_name_after_colon(ln),
                "address": address,
                "phone": phone,
                "postcode": postcode,
                "email": email,
            })
    return contacts


def _extract_name_after_colon(text: str) -> str:
    if "：" in text:
        return text.split("：", 1)[1].strip()
    if ":" in text:
        return text.split(":", 1)[1].strip()
    return text


def _extract_blanks(lines: list[str]) -> list[dict[str, str]]:
    patterns = [r"\bXXX\b", r"\bXX\b", r"____+", r"【\s*】", r"（\s*）", r"‘\s*’", r"“\s*”"]
    out: list[dict[str, str]] = []
    for idx, ln in enumerate(lines, start=1):
        if any(re.search(p, ln) for p in patterns):
            out.append({"line": idx, "text": ln})
    return out


def _extract_party_name(text: str, role: str) -> str:
    """Extract the party name for the given canonical role ("甲" or "乙").

    Tries 甲方/乙方 first, then falls back to school-template aliases such as
    委托方/研究方/受托方 etc. so the extraction also works for templates that
    do not use the 甲乙方 vocabulary directly.
    """
    role = role.strip()
    if role.endswith("方"):
        role = role[:-1]
    canonical = (role + "方") if role else ""
    aliases = [a for a, r in _PARTY_ROLE_ALIASES.items() if r == role]
    # Always try the canonical 甲方/乙方 first, then aliases.
    if canonical and canonical not in aliases:
        aliases = [canonical] + aliases
    # Prefer canonical first, then longer aliases (more specific).
    aliases.sort(key=lambda x: (0 if x == canonical else 1, -len(x)))

    patterns: list[str] = []
    for alias in aliases:
        # alias followed by optional supplementary parenthesised label, then ：/: and the value
        patterns.append(rf"{alias}[ \t　]*(?:[（(][^）)\n]+[)）])?[ \t　]*[：:][ \t　]*[【\[]([^】\]\n]+)[】\]]")
        patterns.append(rf"{alias}[ \t　]*(?:[（(][^）)\n]+[)）])?[ \t　]*[：:][ \t　]*([^\n]+)")
        # alias appearing inside a parenthesised label after the value: "中山大学（甲方）"
        patterns.append(rf"([\u4e00-\u9fa5A-Za-z0-9·.\-（）()&]+?)\s*[（(]\s*{alias}\s*[)）]")

    other_aliases = [k for k in _PARTY_ROLE_ALIASES if _PARTY_ROLE_ALIASES[k] != role]
    other_re = "|".join(re.escape(a) for a in other_aliases) or "甲方|乙方"

    for p in patterns:
        m = re.search(p, text)
        if not m:
            continue
        val = m.group(1).strip()
        # cut off when the next party label appears in the same line
        val = re.split(rf"\s+(?:{other_re})[：:（(]", val)[0].strip()
        # also trim trailing role label that crept in (e.g. "中山大学甲方")
        for alias in _PARTY_ROLE_ALIASES:
            if val.endswith(alias):
                val = val[: -len(alias)].strip(" 　:：、（）()【】[]")
        cleaned = val.strip("【】[]（）() 　:：")
        # Reject clearly-not-a-name patterns: checkbox markers, sentence chars, page numbers
        if not cleaned or len(cleaned) < 2:
            continue
        if any(ch in cleaned for ch in "□☑■◇◆。；;"):
            continue
        # Reject signature-page placeholders without real content
        if cleaned in {"盖章", "签名", "签章", "签字", "印章", "公章"}:
            continue
        return cleaned
    return ""
