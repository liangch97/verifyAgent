from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def load_contract(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _load_docx(path)
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return {
            "source_file": str(path),
            "source_type": suffix,
            "ordered_blocks": [{"location": "text-1", "type": "paragraph", "text": text}],
            "comments": [],
            "text": text,
        }
    raise ValueError(f"暂不支持的文件类型: {suffix}")


def _load_pdf(path: Path) -> dict[str, Any]:
    text_parts: list[str] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        for idx, page in enumerate(reader.pages, start=1):
            txt = page.extract_text() or ""
            text_parts.append(txt)
    except Exception:
        text_parts = []
    ordered = [{"location": f"pdf-page-{i+1}", "type": "paragraph", "text": t} for i, t in enumerate(text_parts)]
    text = "\n".join([b["text"] for b in ordered if b.get("text")])
    return {
        "source_file": str(path),
        "source_type": ".pdf",
        "ordered_blocks": ordered,
        "comments": [],
        "text": text,
    }


def _load_docx(path: Path) -> dict[str, Any]:
    from docx import Document
    from docx.document import Document as _Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    def iter_block_items(parent):
        if isinstance(parent, _Document):
            parent_elm = parent.element.body
        else:
            parent_elm = parent._tc
        for child in parent_elm.iterchildren():
            if child.tag.endswith("}p"):
                yield Paragraph(child, parent)
            elif child.tag.endswith("}tbl"):
                yield Table(child, parent)

    doc = Document(str(path))
    ordered_blocks: list[dict[str, str]] = []
    p_idx = 0
    t_idx = 0
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            p_idx += 1
            text = (block.text or "").strip()
            ordered_blocks.append({"location": f"p-{p_idx}", "type": "paragraph", "text": text})
        elif isinstance(block, Table):
            t_idx += 1
            for r_idx, row in enumerate(block.rows, start=1):
                cell_texts = []
                for c_idx, cell in enumerate(row.cells, start=1):
                    val = re.sub(r"\s+", " ", (cell.text or "")).strip()
                    cell_texts.append(val)
                    ordered_blocks.append(
                        {
                            "location": f"t-{t_idx}-r{r_idx}-c{c_idx}",
                            "type": "table_cell",
                            "text": val,
                        }
                    )
                ordered_blocks.append(
                    {
                        "location": f"t-{t_idx}-r{r_idx}",
                        "type": "table_row",
                        "text": " | ".join([c for c in cell_texts if c]),
                    }
                )

    comments = _extract_docx_comments(path)
    highlights = _extract_docx_highlights(path)
    text = "\n".join([b["text"] for b in ordered_blocks if b.get("text")])
    return {
        "source_file": str(path),
        "source_type": ".docx",
        "ordered_blocks": ordered_blocks,
        "comments": comments,
        "highlights": highlights,
        "text": text,
    }


def _extract_docx_comments(path: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if "word/comments.xml" not in zf.namelist():
                return out
            comments_root = ET.fromstring(zf.read("word/comments.xml"))
            doc_root = ET.fromstring(zf.read("word/document.xml"))

            anchors: dict[str, list[str]] = {}
            for comment in comments_root.findall("w:comment", ns):
                cid = comment.attrib.get(f"{{{ns['w']}}}id", "")
                anchors[cid] = []

            active: list[str] = []
            start_tag = f"{{{ns['w']}}}commentRangeStart"
            end_tag = f"{{{ns['w']}}}commentRangeEnd"
            text_tag = f"{{{ns['w']}}}t"

            def walk(el: ET.Element) -> None:
                if el.tag == start_tag:
                    cid = el.attrib.get(f"{{{ns['w']}}}id", "")
                    active.append(cid)
                elif el.tag == end_tag:
                    cid = el.attrib.get(f"{{{ns['w']}}}id", "")
                    if cid in active:
                        active.remove(cid)
                elif el.tag == text_tag and el.text:
                    for cid in active:
                        if cid in anchors:
                            anchors[cid].append(el.text)
                for child in list(el):
                    walk(child)

            walk(doc_root)

            for comment in comments_root.findall("w:comment", ns):
                cid = comment.attrib.get(f"{{{ns['w']}}}id", "")
                pieces: list[str] = []
                for t in comment.findall(".//w:t", ns):
                    if t.text:
                        pieces.append(t.text)
                text = "".join(pieces).strip()
                out.append({"id": cid, "anchor": "".join(anchors.get(cid, [])).strip(), "text": text})
    except Exception:
        return out
    return out


def _extract_docx_highlights(path: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(path, "r") as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
        for idx, para in enumerate(root.findall(".//w:p", ns), start=1):
            highlighted: list[str] = []
            highlight_values: list[str] = []
            for run in para.findall(".//w:r", ns):
                highlight = run.find("w:rPr/w:highlight", ns)
                shading = run.find("w:rPr/w:shd", ns)
                shaded = (
                    shading is not None
                    and shading.attrib.get(f"{{{ns['w']}}}fill") not in {None, "auto", "FFFFFF"}
                )
                if highlight is None and not shaded:
                    continue
                text = "".join(t.text or "" for t in run.findall(".//w:t", ns))
                if not text.strip():
                    continue
                highlighted.append(text)
                if highlight is not None:
                    highlight_values.append(highlight.attrib.get(f"{{{ns['w']}}}val", ""))
            if highlighted:
                paragraph = "".join(t.text or "" for t in para.findall(".//w:t", ns)).strip()
                out.append(
                    {
                        "location": f"p-{idx}",
                        "text": "".join(highlighted).strip(),
                        "paragraph": paragraph,
                        "highlight": ",".join([v for v in highlight_values if v]),
                    }
                )
    except Exception:
        return out
    return out
