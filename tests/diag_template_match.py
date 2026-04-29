import sys, json
from pathlib import Path
sys.path.insert(0, "/root/contract-review-openclaw-portable")
from scripts.template_matcher import detect_template_match, load_templates, resolve_templates_dir

td = resolve_templates_dir()
print(f"templates_dir: {td}")
templates = load_templates(td)
print(f"templates loaded: {list(templates.keys())}")

PCDW = Path("/mnt/d/行政agent/科研项目常用范本合同/sample/PCDW弯道偏离预警功能误触发软件不良分析技术服务合同67500元-合并附件20260224.docx")
from scripts.contract_loader import load_contract
loaded = load_contract(PCDW)
text = "\n".join(b.get("text","") for b in loaded.get("ordered_blocks",[]))
result = detect_template_match(text, contract_path=PCDW)
print("\n=== detect_template_match result ===")
if result:
    print(f"matched template: {result.get('template_name')}")
    print(f"similarity: {result.get('similarity'):.3f}" if result.get('similarity') else None)
    print(f"diff clauses: {len(result.get('diffs', []))}")
    for d in (result.get('diffs') or [])[:3]:
        print(f"  - {d}")
else:
    print("(no match)")
