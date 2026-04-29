import sys, time
md = open("/root/contract-review-openclaw-portable/output/im_review/20260429_172257/contract_review.md", encoding="utf-8").read()
lines = md.splitlines()
print(f"total lines={len(lines)} chars={len(md)} max-line-len={max(len(l) for l in lines)}")
print("Top-5 long lines:")
for l in sorted(lines, key=len, reverse=True)[:5]:
    print(f"  len={len(l)} :: {l[:120]!r}…")

# Try the actual render
sys.path.insert(0, "/root")
sys.path.insert(0, "/root/contract-review-openclaw-portable")
import importlib
adm = importlib.import_module("admin_report")
import json
findings = json.load(open("/root/contract-review-openclaw-portable/output/im_review/20260429_172257/contract_findings_18be052dc05d.json", encoding="utf-8"))
from pathlib import Path
out = Path("/tmp/test_admin_render.pdf")
contract_path = Path("dummy.docx")  # will trigger _safe_filename
t0 = time.time()
adm.render_admin_pdf(rule_extracted={}, llm_extracted={}, company_check={}, md_text=md, contract_path=contract_path, output_pdf=out)
print(f"render-time={time.time()-t0:.1f}s out-size={out.stat().st_size}")
