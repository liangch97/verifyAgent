import sys, json, time
from pathlib import Path

sys.path.insert(0, "/root")
sys.path.insert(0, "/root/contract-review-openclaw-portable")

PCDW = Path("/mnt/d/行政agent/科研项目常用范本合同/sample/PCDW弯道偏离预警功能误触发软件不良分析技术服务合同67500元-合并附件20260224.docx")
PREV_REPORT = Path("/root/contract-review-openclaw-portable/output/im_review/20260429_172257/合同审核报告_行政版.pdf")

print(f"=== PCDW sample exists: {PCDW.exists()} ===")
print(f"=== Previous report exists: {PREV_REPORT.exists()} ===")

# 1) extractor: should pull party_a
from scripts.contract_loader import load_contract
from scripts.contract_extractor import extract_contract

t0 = time.time()
loaded = load_contract(PCDW)
print(f"load_contract took {time.time()-t0:.2f}s, blocks={len(loaded.get('ordered_blocks',[]))}")

t0 = time.time()
ext = extract_contract(loaded)
print(f"extract_contract took {time.time()-t0:.2f}s")
pa = ext.get("party_a"); pb = ext.get("party_b")
print(f"party_a={pa}")
print(f"party_b={pb}")
print(f"contract_name={ext.get('contract_name')}")
print(f"amount={ext.get('amount')}")

# 2) previous-report detector
from full_qcc_review import looks_like_previous_report
print(f"\nlooks_like_previous_report(PCDW) = {looks_like_previous_report(PCDW)}  (expected False)")
print(f"looks_like_previous_report(PREV_REPORT) = {looks_like_previous_report(PREV_REPORT)}  (expected True)")

# 3) admin pdf render with mock md
import admin_report as adm
md_text = """# 合同形式化审核报告\n\n## 审核结论\n\n基本可审，建议人工复核。\n\n## 必须修复事项\n\n| 序号 | 事项 | 关联条款 | 风险说明 | 建议处理 |\n| --- | --- | --- | --- | --- |\n| 1 | 测试 | 第1条 | 普通风险 | 修改 |\n"""
out = Path("/tmp/pcdw_admin_test.pdf")
t0 = time.time()
adm.render_admin_pdf(rule_extracted=ext, llm_extracted={}, company_check={}, md_text=md_text, contract_path=PCDW, output_pdf=out)
print(f"\nrender_admin_pdf took {time.time()-t0:.2f}s, size={out.stat().st_size}")
