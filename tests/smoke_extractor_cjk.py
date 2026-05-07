import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.contract_extractor import _extract_party_name

cases = [
    "甲方：华为技术有限公 司\n乙方：中山大学",
    "甲方：  华为技术有限公司  \n乙方：中山大学",
    "甲方：华为技术 有限\t公司\n乙方：中山大学",
    "甲方：Acme Corp.\n乙方：中山大学",
]
for c in cases:
    print(repr(c[:30]), "->", repr(_extract_party_name(c, "甲")))
