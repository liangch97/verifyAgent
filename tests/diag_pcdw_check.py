import sys
from pathlib import Path
sys.path.insert(0, "/root/contract-review-openclaw-portable")
from scripts.contract_loader import load_contract
from scripts.contract_extractor import extract_contract
loaded = load_contract(Path("/mnt/d/行政agent/科研项目常用范本合同/sample/PCDW弯道偏离预警功能误触发软件不良分析技术服务合同67500元-合并附件20260224.docx"))
ext = extract_contract(loaded)
print("party_a:", ext.get("party_a"))
print("party_b:", ext.get("party_b"))
print("contract_name:", ext.get("contract_name"))
print("amount:", ext.get("amount"))
