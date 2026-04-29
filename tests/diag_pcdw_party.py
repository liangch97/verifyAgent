import sys, json
from pathlib import Path

sys.path.insert(0, "/root/contract-review-openclaw-portable")

PCDW = Path("/mnt/d/行政agent/科研项目常用范本合同/sample/PCDW弯道偏离预警功能误触发软件不良分析技术服务合同67500元-合并附件20260224.docx")

from scripts.contract_loader import load_contract
loaded = load_contract(PCDW)
text = "\n".join(b.get("text","") for b in loaded.get("ordered_blocks",[]))
print(f"=== text length: {len(text)} ===\n")
# Show first 3000 chars
print(text[:3000])
print("\n--- LOOKING FOR PARTY MARKERS ---")
import re
for keyword in ["甲方","乙方","委托方","受托方","项目委托方","项目受托方","技术服务方","技术受托方","委托人","受托人"]:
    for m in re.finditer(rf"{keyword}[：:（(]?[^\n]{{0,80}}", text):
        print(f"  {keyword}@{m.start()}: {m.group(0)[:120]!r}")
