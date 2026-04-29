import sys
sys.path.insert(0, "/root")
import full_qcc_review as fqr
print("FEISHU_ENABLED:", fqr._FEISHU_ENABLED)
print("APP_ID len:", len(fqr.APP_ID))
print("DEMO_DIR:", fqr.DEMO_DIR)
# Smoke test fs_text no-op
fqr.fs_text("hello (this should print as fs_text(disabled))")
print("OK import")
