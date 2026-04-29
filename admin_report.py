"""Admin-friendly contract review PDF renderer.

Inputs:
- rule_extracted (dict from scripts.contract_extractor)
- llm_extracted (dict from llm_field_extract.llm_extract)
- company_check (dict from QCC, with 'fields' key)
- md_text (full contract_review.md text — used to extract the action-item tables)
- output_pdf (Path)

Produces a single PDF with: 摘要 / 合同基本信息 / 工商核查 / 建议先修改 / 需人工确认 / 信息提示。
No rule IDs, no dual-track section, no archived items.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from datetime import datetime


def _pick(*vals) -> str:
    """Return first non-empty stringified value."""
    for v in vals:
        if v is None:
            continue
        if isinstance(v, dict):
            n = v.get("name")
            if n: return str(n).strip()
            continue
        s = str(v).strip()
        if s and s.lower() not in ("none", "null", "—", "-"):
            return s
    return ""


_MOJIBAKE_HINTS = set("åæäèçñëïüÅÆÄÈÇÑËÏÜÃÂÔÕÖÝÞßçÇÉÊËÍÎÏÓÔÕÖÚÛÜ")


def _looks_like_mojibake(name: str) -> bool:
    """Heuristic: filename downloaded from IM with UTF-8 bytes mis-decoded as
    Latin-1 / CP1252. The result has many `å æ ä è ç` characters interleaved
    with `_` placeholders for control bytes."""
    if not name:
        return False
    hits = sum(1 for ch in name if ch in _MOJIBAKE_HINTS)
    return hits >= 3


def _safe_filename(name: str) -> str:
    """Display-friendly source filename: drop mojibake-looking part, keep
    the trailing UUID/extension as a stable identifier."""
    if not name:
        return "—"
    if not _looks_like_mojibake(name):
        return name
    # Try to keep the trailing -<uuid>.<ext>
    m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.([A-Za-z0-9]+)$", name)
    if m:
        return f"(原始文件名编码异常) …{m.group(1)[-12:]}.{m.group(2)}"
    suffix = name.rsplit(".", 1)[-1] if "." in name else "bin"
    return f"(原始文件名编码异常).{suffix}"


def _truncate(value: str, max_len: int = 600) -> str:
    """Cap a single table-cell value. Long polluted text from PDF extraction
    can blow weasyprint layout time from seconds to minutes."""
    if not value:
        return value
    s = str(value)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def merged_basic_info(rule: dict, llm: dict, contract_path: Path) -> dict[str, str]:
    """Merge rule+llm, prefer the more accurate value."""
    r_pa = rule.get("party_a") or {}
    r_pb = rule.get("party_b") or {}
    l_pa = (llm.get("party_a") or {}) if isinstance(llm.get("party_a"), dict) else {}
    l_pb = (llm.get("party_b") or {}) if isinstance(llm.get("party_b"), dict) else {}

    # title: rule often pollutes with "甲方:[]乙方:[]"; prefer LLM if clean
    rule_title = _pick(rule.get("title"))
    llm_title = _pick(llm.get("title"))
    if "甲方" in rule_title or "乙方" in rule_title or "【" in rule_title:
        title = llm_title or rule_title
    else:
        title = rule_title or llm_title

    # amount: rule.amount can be dict {value,...} or empty; LLM has amount_yuan
    rule_amt = rule.get("amount")
    if isinstance(rule_amt, dict):
        rule_amt_val = rule_amt.get("value") or rule_amt.get("text")
    else:
        rule_amt_val = rule_amt
    amount = _pick(rule_amt_val, llm.get("amount_yuan"), llm.get("amount_text"))
    if amount and amount.replace(".", "", 1).isdigit():
        amount = f"人民币 {float(amount):,.2f} 元"

    return {
        "标题": title,
        "合同编号": _pick(rule.get("contract_no"), llm.get("contract_no")),
        "合同类型": _pick(rule.get("contract_type"), llm.get("contract_type")),
        "项目名称": _pick(rule.get("project_name"), llm.get("project_name")) or "（未识别）",
        "甲方名称": _pick(r_pa.get("name"), l_pa.get("name")),
        "甲方信用代码": _pick(r_pa.get("credit_code"), l_pa.get("credit_code")) or "—",
        "甲方地址": _pick(r_pa.get("address"), l_pa.get("address")) or "—",
        "甲方法定代表人": _pick(r_pa.get("legal_rep"), l_pa.get("legal_rep")) or "—",
        "乙方名称": _pick(r_pb.get("name"), l_pb.get("name")),
        "乙方地址": _pick(r_pb.get("address"), l_pb.get("address")) or "—",
        "签署日期": _pick(llm.get("sign_date"), rule.get("sign_date")) or "—",
        "履行起止": _pick(
            f"{llm.get('perform_start','')} 至 {llm.get('perform_end','')}".strip(" 至 ")
        ) or "—",
        "合同金额": amount or "—",
        "源文件": _safe_filename(contract_path.name),
    }


def qcc_compare_rows(merged: dict, company_check: dict) -> list[dict]:
    """Build comparison: 合同声称 vs QCC 抓取 for party A."""
    fields = (company_check or {}).get("fields", {}) or {}
    rows = []

    def _row(label: str, claimed: str, fetched: str):
        ok = bool(claimed and fetched and claimed.strip() == fetched.strip())
        partial = bool(claimed and fetched and not ok and (claimed in fetched or fetched in claimed))
        if ok:
            verdict = "一致"
        elif partial:
            verdict = "包含/部分一致"
        elif not fetched:
            verdict = "未抓取到"
        elif not claimed:
            verdict = "合同未声明"
        else:
            verdict = "不一致 ⚠"
        return {"项目": label, "合同声称": claimed or "—", "工商抓取": fetched or "—", "结论": verdict}

    rows.append(_row("企业名称", merged.get("甲方名称", ""), _pick(fields.get("name"), fields.get("企业名称"))))
    rows.append(_row("统一社会信用代码", merged.get("甲方信用代码", "").replace("—", ""),
                     _pick(fields.get("credit_code"), fields.get("统一社会信用代码"))))
    rows.append(_row("法定代表人", merged.get("甲方法定代表人", "").replace("—", ""),
                     _pick(fields.get("legal_rep"), fields.get("法定代表人"))))
    rows.append(_row("注册地址", merged.get("甲方地址", "").replace("—", ""),
                     _pick(fields.get("registered_address"), fields.get("address"),
                           fields.get("注册地址"), fields.get("住所"))))
    rows.append(_row("经营状态", "",
                     _pick(fields.get("company_status"), fields.get("status"), fields.get("经营状态"))))
    rows.append(_row("成立日期", "",
                     _pick(fields.get("established_date"), fields.get("establish_date"), fields.get("成立日期"))))
    rows.append(_row("注册资本", "",
                     _pick(fields.get("registered_capital"), fields.get("capital"), fields.get("注册资本"))))
    rows.append(_row("企业类型", "",
                     _pick(fields.get("company_type"), fields.get("企业类型"))))
    rows.append(_row("企业规模", "",
                     _pick(fields.get("company_scale"), fields.get("企业规模"))))
    rows.append(_row("员工人数", "",
                     _pick(fields.get("employee_count"), fields.get("员工人数"))))
    rows.append(_row("所属行业", "",
                     _pick(fields.get("industry"), fields.get("所属行业"))))
    rows.append(_row("联系电话", "", _pick(fields.get("phone"), fields.get("电话"))))
    rows.append(_row("电子邮箱", "", _pick(fields.get("email"), fields.get("邮箱"))))
    rows.append(_row("企业官网", "", _pick(fields.get("website"), fields.get("官网"))))
    rows.append(_row("经营范围", "",
                     _pick(fields.get("business_scope"), fields.get("经营范围"))))
    return rows


# ===== Parse md tables =====
_SECTIONS = {
    "fix": "### 1.1 建议先修改的事项",
    "manual": "### 1.2 需要人工确认或补充材料的事项",
    "info": "### 1.3 信息提示",
}


def _extract_section_table(md_text: str, header: str) -> list[dict]:
    """Extract markdown table rows under a section header."""
    idx = md_text.find(header)
    if idx == -1:
        return []
    # Find next section start (### or ##)
    rest = md_text[idx + len(header):]
    next_sec = re.search(r"\n#{2,3} ", rest)
    block = rest[:next_sec.start()] if next_sec else rest
    rows = []
    in_table = False
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("|") and "---" in line:
            in_table = True
            continue
        if line.startswith("|") and in_table:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 5:
                rows.append({
                    "序号": cells[0],
                    "事项": cells[1],
                    "关联条款": cells[2],
                    "风险说明": cells[3],
                    "建议处理": cells[4],
                })
        elif in_table and not line.startswith("|"):
            in_table = False
    return rows


def _parse_decision(md_text: str) -> tuple[str, str, str]:
    """Extract decision, confidence, summary."""
    decision = confidence = ""
    for ln in md_text.splitlines()[:15]:
        if "审核结论" in ln:
            decision = ln.split("：", 1)[-1].replace("**", "").strip()
        elif "置信度" in ln:
            confidence = ln.split("：", 1)[-1].strip()
    # counts
    counts = {}
    m = re.search(r"建议先修改事项[：:]\s*(\d+)\s*项", md_text)
    if m: counts["fix"] = m.group(1)
    m = re.search(r"需要人工确认事项[：:]\s*(\d+)\s*项", md_text)
    if m: counts["manual"] = m.group(1)
    m = re.search(r"提示事项[：:]\s*(\d+)\s*项", md_text)
    if m: counts["info"] = m.group(1)
    summary = (
        f"建议先修改 {counts.get('fix','0')} 项；"
        f"需人工确认 {counts.get('manual','0')} 项；"
        f"信息提示 {counts.get('info','0')} 项。"
    )
    return decision, confidence, summary


# ===== HTML rendering =====
def _h(text: str) -> str:
    """HTML escape."""
    return (str(text or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _table(headers: list[str], rows: list[list[str]], col_widths: list[str] | None = None) -> str:
    if not rows:
        return "<p class='empty'>（本节无内容）</p>"
    cw = ""
    if col_widths:
        cw = "<colgroup>" + "".join(f"<col style='width:{w}'>" for w in col_widths) + "</colgroup>"
    th = "".join(f"<th>{_h(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{_h(c)}</td>" for c in r) + "</tr>"
    return f"<table>{cw}<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


_TEMPLATE_STATUS_LABEL = {
    "unchanged": "未改动",
    "modified": "有修改",
    "rewritten": "重大改写",
    "removed": "范本中存在但合同未见",
    "added": "合同新增",
}


def _render_template_section(rule_extracted: dict) -> str:
    tm = (rule_extracted or {}).get("template_match") or {}
    if not tm or tm.get("error"):
        msg = tm.get("error") if tm else "未配置范本合同库"
        return (
            "<section>"
            "<h2>三、学校范本对照</h2>"
            f"<p class='hint'>{_h('范本对照不可用：' + (msg or ''))}</p>"
            "</section>"
        )
    if not tm.get("matched"):
        sim = tm.get("similarity") or 0.0
        best = tm.get("template_name") or "（无）"
        return (
            "<section>"
            "<h2>三、学校范本对照</h2>"
            f"<p class='hint'>未识别为现有学校范本（最相似：{_h(best)}，相似度 {sim:.0%}）。"
            "已按通用规则审查。</p>"
            "</section>"
        )
    sim = tm.get("similarity") or 0.0
    name = tm.get("template_name") or "未知范本"
    counts = tm.get("counts") or {}
    modified_n = tm.get("modified_count") or 0
    summary = tm.get("summary") or ""
    rows = []
    for idx, c in enumerate(tm.get("clauses") or [], start=1):
        status = c.get("status", "")
        label = _TEMPLATE_STATUS_LABEL.get(status, status)
        ratio = c.get("diff_ratio")
        ratio_txt = f"{ratio:.0%}" if isinstance(ratio, (int, float)) else "-"
        rows.append([
            str(idx),
            c.get("title") or c.get("id") or "",
            label,
            ratio_txt,
            (c.get("template_excerpt") or "")[:120],
            (c.get("contract_excerpt") or "")[:120],
        ])
    badge_class = "warn" if modified_n else "info"
    badge_text = f"{modified_n} 处修改" if modified_n else "条款未改动"
    header = (
        f"<p class='hint'>识别为学校范本：<b>{_h(name)}</b>（整体相似度 {sim:.0%}）。"
        f"未改动 {counts.get('unchanged', 0)} / 修改 {counts.get('modified', 0)} / "
        f"改写 {counts.get('rewritten', 0)} / 缺失 {counts.get('removed', 0)} / "
        f"新增 {counts.get('added', 0)}。{_h(summary)}</p>"
    )
    return (
        "<section>"
        f"<h2>三、学校范本对照 <span class='badge {badge_class}'>{badge_text}</span></h2>"
        f"{header}"
        + _table(
            ["序号", "条款", "状态", "差异度", "范本摘要", "合同摘要"],
            rows,
            ["5%", "20%", "12%", "8%", "27%", "28%"],
        )
        + "</section>"
    )



def render_admin_pdf(
    *,
    rule_extracted: dict,
    llm_extracted: dict,
    company_check: dict,
    md_text: str,
    contract_path: Path,
    output_pdf: Path,
) -> Path:
    """Generate the admin-friendly PDF."""
    from weasyprint import HTML, CSS

    merged = merged_basic_info(rule_extracted, llm_extracted, contract_path)
    decision, confidence, summary = _parse_decision(md_text)
    qcc_rows = qcc_compare_rows(merged, company_check)

    # Decision color
    decision_class = "ok" if "可审" in decision and "不" not in decision else "warn"
    if "不予" in decision or "拒" in decision:
        decision_class = "bad"

    # Basic info as 2-col rows
    basic_rows = [[k, _truncate(v, 400)] for k, v in merged.items()]

    fix_items = _extract_section_table(md_text, _SECTIONS["fix"])
    manual_items = _extract_section_table(md_text, _SECTIONS["manual"])
    info_items = _extract_section_table(md_text, _SECTIONS["info"])

    def _items_to_rows(items: list[dict]) -> list[list[str]]:
        return [[
            it["序号"],
            _truncate(it["事项"], 80),
            _truncate(it["关联条款"], 600),
            _truncate(it["风险说明"], 600),
            _truncate(it["建议处理"], 400),
        ] for it in items]

    qcc_table_rows = [[r["项目"], _truncate(r["合同声称"], 200), _truncate(r["工商抓取"], 200), r["结论"]] for r in qcc_rows]

    template_section_html = _render_template_section(rule_extracted)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>合同审核报告</title></head>
<body>
  <header class="cover">
    <h1>合同形式化审核报告</h1>
    <div class="meta">
      <div><span class="lbl">合同名称：</span>{_h(merged.get('标题') or merged.get('源文件'))}</div>
      <div><span class="lbl">生成时间：</span>{now}</div>
    </div>
  </header>

  <section class="verdict {decision_class}">
    <div class="verdict-row">
      <span class="verdict-label">审核结论</span>
      <span class="verdict-value">{_h(decision or '未识别')}</span>
      <span class="verdict-conf">置信度 {_h(confidence or 'N/A')}</span>
    </div>
    <p class="summary">{_h(summary)}</p>
  </section>

  <section>
    <h2>一、合同基本信息</h2>
    {_table(["项目", "内容"], basic_rows, ["28%", "72%"])}
  </section>

  <section>
    <h2>二、甲方工商核查对照</h2>
    <p class="hint">数据来源：企查查（QCC）实时抓取；与合同声称内容逐项比对。</p>
    {_table(["核查项", "合同声称", "工商抓取", "比对结论"], qcc_table_rows, ["20%", "30%", "35%", "15%"])}
  </section>

  {template_section_html}

  <section>
    <h2>四、建议先修改的事项 <span class="badge bad">{len(fix_items)} 项</span></h2>
    {_table(["序号", "事项", "关联条款/证据", "风险说明", "建议处理"],
            _items_to_rows(fix_items), ["5%", "16%", "26%", "26%", "27%"])}
  </section>

  <section>
    <h2>五、需要人工确认或补充材料 <span class="badge warn">{len(manual_items)} 项</span></h2>
    {_table(["序号", "事项", "关联条款/证据", "风险说明", "建议处理"],
            _items_to_rows(manual_items), ["5%", "16%", "26%", "26%", "27%"])}
  </section>

  <section>
    <h2>六、信息提示 <span class="badge info">{len(info_items)} 项</span></h2>
    {_table(["序号", "事项", "关联条款/证据", "风险说明", "建议处理"],
            _items_to_rows(info_items), ["5%", "16%", "26%", "26%", "27%"])}
  </section>

  <footer>
    <p>本报告由合同形式化审核系统自动生成，结合规则引擎与智能字段补全，仅供行政审核参考。最终结论以人工复核为准。</p>
  </footer>
</body></html>
"""

    css = """
@page { size: A4; margin: 16mm 14mm 16mm 14mm;
    @bottom-center { content: "第 " counter(page) " / " counter(pages) " 页"; font-size: 8pt; color: #888; }
}
html { font-family: 'Noto Sans CJK SC','Noto Sans CJK HK',sans-serif; font-size: 10pt; line-height: 1.55; color: #1f2937; }
body { margin: 0; }
.cover { border-bottom: 3px solid #1e40af; padding-bottom: 10px; margin-bottom: 14px; }
.cover h1 { font-size: 22pt; color: #1e3a8a; margin: 0 0 6px 0; font-weight: 700; }
.cover .meta { font-size: 9.5pt; color: #4b5563; }
.cover .meta .lbl { color: #1e40af; font-weight: 600; }
.cover .meta div { margin-top: 3px; }

.verdict { background: #f8fafc; border-left: 5px solid #2563eb; padding: 10px 14px; margin: 12px 0 16px; border-radius: 4px; }
.verdict.warn { border-left-color: #d97706; background: #fffbeb; }
.verdict.bad { border-left-color: #dc2626; background: #fef2f2; }
.verdict.ok { border-left-color: #059669; background: #ecfdf5; }
.verdict-row { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.verdict-label { font-size: 10pt; color: #6b7280; font-weight: 600; }
.verdict-value { font-size: 14pt; font-weight: 700; color: #111827; }
.verdict-conf { font-size: 9.5pt; color: #6b7280; margin-left: auto; }
.summary { margin: 6px 0 0; font-size: 10pt; color: #374151; }

h2 { font-size: 13pt; color: #1e3a8a; margin: 18px 0 6px; padding-bottom: 4px; border-bottom: 1px solid #cbd5e1; }
h2 .badge { font-size: 9pt; padding: 2px 8px; border-radius: 10px; margin-left: 6px; vertical-align: middle; font-weight: 500; }
h2 .badge.bad { background: #fee2e2; color: #b91c1c; }
h2 .badge.warn { background: #fef3c7; color: #b45309; }
h2 .badge.info { background: #dbeafe; color: #1e40af; }

p.hint { font-size: 9pt; color: #6b7280; margin: 4px 0 6px; }
p.empty { font-size: 9.5pt; color: #94a3b8; font-style: italic; padding: 6px 4px; }

table { border-collapse: collapse; width: 100%; margin: 4px 0 8px; table-layout: fixed; }
th, td { border: 1px solid #cbd5e1; padding: 5px 7px; vertical-align: top; font-size: 9pt; word-wrap: break-word; overflow-wrap: break-word; }
th { background: #eff6ff; color: #1e40af; font-weight: 600; text-align: left; }
tbody tr:nth-child(even) { background: #f8fafc; }

footer { margin-top: 22px; padding-top: 8px; border-top: 1px dashed #cbd5e1; font-size: 8.5pt; color: #6b7280; text-align: center; }

section { page-break-inside: auto; }
table { page-break-inside: auto; }
tr { page-break-inside: avoid; page-break-after: auto; }
thead { display: table-header-group; }
"""

    HTML(string=html).write_pdf(str(output_pdf), stylesheets=[CSS(string=css)])
    return output_pdf


if __name__ == "__main__":
    # smoke test
    import sys, json
    sys.path.insert(0, "/root")
    sys.path.insert(0, "/root/contract-review-openclaw-portable")
    from llm_field_extract import llm_extract
    from scripts.contract_loader import load_contract
    from scripts.contract_extractor import extract_contract

    contract = Path(sys.argv[1] if len(sys.argv) > 1 else
                    "/root/contract-review-openclaw-portable/samples/华为-中大智算集群可靠性测评技术合作协议-脱敏版.docx")
    md_path = Path(sys.argv[2] if len(sys.argv) > 2 else
                   "/root/contract-review-openclaw-portable/output/im_review/20260429_010524/contract_review.md")
    cc_path = Path(sys.argv[3] if len(sys.argv) > 3 else
                   "/root/contract-review-openclaw-portable/samples/company_check_huawei.json")
    out_pdf = md_path.parent / "合同审核报告_行政版.pdf"

    loaded = load_contract(contract)
    rule_ext = extract_contract(loaded)
    raw = "\n".join(b.get("text", "") for b in loaded.get("ordered_blocks", []))
    llm_ext = llm_extract(raw)
    cc = json.loads(cc_path.read_text(encoding="utf-8")) if cc_path.exists() else {}
    md_text = md_path.read_text(encoding="utf-8")

    p = render_admin_pdf(
        rule_extracted=rule_ext,
        llm_extracted=llm_ext,
        company_check=cc,
        md_text=md_text,
        contract_path=contract,
        output_pdf=out_pdf,
    )
    print(f"[admin pdf] {p} size={p.stat().st_size}")
