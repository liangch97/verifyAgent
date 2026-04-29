import sys, os
# qcc_login_demo helpers
sys.path.insert(0, "/root/contract-review-openclaw-portable/scripts")
from qcc_login_demo import _normalize_company_name, _name_visible_in
print("normalize:", _normalize_company_name("华为 技术\t有限公司"))
print("visible1:", _name_visible_in("华为技术有限公 司", "页面：华为技术有限公司，统一信用代码…"))
print("visible2:", _name_visible_in("华为技术有限公司", "页面：华为 技术有限公司"))
print("visible3:", _name_visible_in("华为技术有限公司", "无关页面"))

# admin_report helpers
sys.path.insert(0, "/root")
from admin_report import _safe_filename, _truncate, _looks_like_mojibake
moji = "å_ä_º-ä_å_æ_ºç_é_---9edc3e84-1234.docx"
clean = "华为合同.docx"
print("mojibake?", _looks_like_mojibake(moji), _looks_like_mojibake(clean))
print("safe:", _safe_filename(moji))
print("safe-clean:", _safe_filename(clean))
print("trunc:", _truncate("a" * 1000, 50))
