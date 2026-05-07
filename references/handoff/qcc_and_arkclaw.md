# QCC and ArkClaw Handoff Reference

Detailed notes referenced from `skills/contract-formal-review-flow/SKILL.md`.
This document holds material that the main SKILL.md links to but does not
need to keep inline (it bloated the SKILL.md and degraded skill comprehension).

## QCC Verification (already wrapped by `full_qcc_review.py`)

`full_qcc_review.py` already handles:

- Local browser-profile reuse (`.browser-profiles/qcc-demo`).
- QR push to Feishu via openclaw-gateway when configured.
- Polling for login state with auto QR refresh.
- Single-company search for the extracted Party A.
- Captcha / 405 / 403 / rate-limit fallback to rule-only review.
- Final admin PDF generation and Feishu push.

You normally do not need to invoke any QCC script other than
`full_qcc_review.py`. Only fall back to the legacy command below when the
user supplies a prepared `company-check` JSON and explicitly wants to skip
the wrapper:

```bash
python /root/contract-review-openclaw-portable/run_contract_review.py \
  "<contract_file_path>" --company-check "<company_check_file>"
```

The legacy `demos/qcc_contract_review_demo.py` MUST NOT be invoked: it does
not push the QR to Feishu and does not generate the admin PDF.

## Company evidence sources (whitelist)

Company information may be used only from controlled sources:

1. QCC evidence captured by `full_qcc_review.py` in the current run.
2. A prepared `company-check` JSON file provided by the user.
3. 企查查 screenshots, copied page text, or a manual registry record
   provided by the user — extract only the visible fields, treat missing
   fields as unknown.

Never fill company registry fields from model memory, general knowledge, or
"publicly known" facts.

## Cloud ArkClaw / Feishu connector outputs

When packaging outputs for ArkClaw or Feishu, prefer to send:

- `output/contract_review.md` — administrative review report.
- `output/合同形式化审核总表.xlsx` — spreadsheet summary.
- `output/qcc_login_demo/qcc_result_*.png` — QCC result screenshot.
- `output/qcc_login_demo/qcc_login_demo_latest.json` — manifest with status,
  result screenshot path, preview HTML path, draft company-check path.

Do not push QR-login screenshots to group chats unless the user explicitly
asks for a controlled login test.

## Explicit QCC QR-Login Demo (rare)

Only when the user explicitly asks to test QCC QR login or pop up a QCC
scan-login window for the local dashboard:

```bash
python /root/contract-review-openclaw-portable/demos/qcc_login_demo.py \
  "华为技术有限公司" --login-only --hold-seconds 900
```

- Replace the company name as requested. Use the requested hold time when
  given; otherwise keep 900 seconds.
- The browser remains open for `--hold-seconds`. Earlier versions closed
  immediately because `--login-only` defaulted to a zero-second hold; that
  has been fixed but if it ever regresses, always pass `--hold-seconds 900`.
- Reply with the preview HTML path first, then the screenshot path and the
  latest run-record path. Note that dashboard chat bubbles may show paths
  rather than inline images, and that this is only a login demo — it does
  not constitute completed company verification.

Do not continue to query company information after the QR demo unless the
user explicitly asks to continue. Do not bypass captcha, WAF, paywalls, paid
fields, or access restrictions.

## Saved login session

- Lives at `.browser-profiles/qcc-demo` inside the project folder.
- Stores normal browser cookies/local session data, not a managed password.
- May be invalidated by QCC at any time; the next run will then re-prompt
  for QR scan.
- Never include `.browser-profiles/` in portable packages or cloud handoff
  artifacts.
- To clear the saved login state, delete `.browser-profiles/qcc-demo`.
