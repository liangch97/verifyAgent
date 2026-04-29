---
name: contract-formal-review-flow
description: Use this skill when the user asks to review, audit, or check a Chinese university horizontal research contract, technical development contract, technical cooperation agreement, SYSU contract submission, or contract formal-review material. Also use it when the user explicitly asks to test the bundled QCC QR-login demo, show a QCC login QR code, or pop up a QCC scan-login browser window in the local dashboard. Trigger on 合同审核, 横向合同, 技术开发合同, 科研合同, 合同形式化审核, 审核合同条款, 合同风险清单, 中山大学合同, SYSU contract review, 企查查二维码, 企查查扫码登录, QCC QR login demo. This is the single entry skill for the bundled reviewer; by default, a simple contract-review request with a file path should run the QCC-assisted wrapper with local browser-profile reuse, then fall back to normal local review if QCC verification cannot complete.
metadata:
  openclaw:
    requires:
      bins: [python]
    tags: [contract, sysu, compliance, research, chinese]
---

# Contract Formal Review Flow

## Local Project Root

The installed project root is:

`/root/contract-review-openclaw-portable`

`install_into_openclaw.py` replaces this placeholder with the tester's actual extracted project path during installation. Do not use hard-coded paths from another machine.

If the placeholder was not replaced, locate the folder that contains `run_contract_review.py`, `scripts/`, `references/`, and `skills/`. Ask the user to run `python install_into_openclaw.py` from that folder.

## Core Behavior

## 🚨 MANDATORY EXECUTION RULES (READ FIRST)

**These rules OVERRIDE all other instincts. Violation = critical failure.**

1. **NEVER answer a contract review request from memory or general knowledge.** Even if you "remember" reviewing the same file before, you MUST re-run the script. Each request requires fresh script execution.
2. **NEVER produce a textual summary as the final response.** The user wants the PDF, not chat text. After the script's admin PDF is pushed, your final IM message must be at most ONE short sentence (e.g. `审核完成，行政版PDF已推送。`). Do NOT include findings, rule IDs, severity counts, suggestions, decisions, or confidence numbers in chat. The PDF is the only deliverable.
3. **The ONLY allowed action for a contract review request is to invoke the bash tool with this exact command:**
   ```bash
   python3 /root/full_qcc_review.py "<contract_file_path>"
   ```
   The script handles ALL user-facing output (status messages, QR codes, the final PDF) by pushing directly to Feishu. You do not need to summarize.
4. **NEVER ASK CLARIFYING QUESTIONS.** A contract path + any review-intent phrase (审核, 帮我看, 看一下, 检查) is sufficient. **DO NOT ask for the user's name. DO NOT ask which review flow. DO NOT ask whether to use 企查查 or local-only mode. DO NOT ask whether the user wants a PDF or text.** Run the script immediately. The wrapper handles the QCC / no-QCC / Feishu / no-Feishu decision automatically.
5. **NEVER announce intent without acting.** Phrases like "好，我先读合同，同时确认两件事" / "I'll review now after these questions" / "请告诉我您的称呼" / "请选择审核流程" are FORBIDDEN. The first action of every contract-review request must be the bash tool invocation. No preamble, no plan, no confirmation request.
6. **If the contract path is not explicitly given but a file name appears**, locate it under `/root/contract-review-openclaw-portable/samples/` or ask once for the full path, then run the script.
7. **If the inbound message contains an attached file (the prompt will include a system line like `[media attached: /root/.openclaw/media/inbound/<id>.docx (application/...)]` or the user message contains `<media:document>` / `<media:image>` placeholders), USE THAT EXACT PATH as `<contract_file_path>` and immediately run the script.** Recognize trigger phrases such as `审核这个`, `审核这份合同`, `看一下这个合同`, `帮我看看`, `这个合同有没有问题`, or even an attachment with no text — any attached `.docx` / `.pdf` / `.txt` file that appears to be a contract is itself a review request. Do NOT ask the user to retype the path; the path inside the `[media attached: ...]` line IS the file path. Quote the path with double quotes when invoking the command, since it may contain Chinese characters or spaces.

   Examples:
   - Inbound: `[media attached: /root/.openclaw/media/inbound/abc123.docx (application/vnd.openxmlformats-officedocument.wordprocessingml.document)]\n\n审核这个`
     → Run: `python3 /root/full_qcc_review.py "/root/.openclaw/media/inbound/abc123.docx"`
   - Inbound contains only the attached-file line and `<media:document> (合同.docx)` placeholder
     → Still run the script with the path from `[media attached: ...]`. The placeholder is just a label; the real path is in the attached line.

## ❌ FORBIDDEN RESPONSES (do NOT emit any of these)

| Bad response | Why it's wrong |
|---|---|
| `好，先读合同，同时快速确认两件事：你是？这篇合同走哪个审核流程？` | Asks for user name and flow — FORBIDDEN |
| `请问您希望走企查查核验还是仅本地审核？` | Asks for review mode — FORBIDDEN |
| `先读起来了，稍后给您结果` | Announces intent without invoking the tool — FORBIDDEN |
| `请告诉我合同的项目名称和金额` | Re-asks for info already in the file — FORBIDDEN |
| `根据合同内容，我建议关注以下几点……` | Textual summary instead of PDF — FORBIDDEN |

The ONE correct response when an attached contract arrives:
1. Call the bash tool: `python3 /root/full_qcc_review.py "/root/.openclaw/media/inbound/<id>.docx"`
2. Wait for the script to finish.
3. Send exactly one short Feishu reply: `审核完成，行政版PDF已推送。`

## ⚡ IM-Driven Mode (Feishu)

When triggered through Feishu IM, ALWAYS run the integrated wrapper which pushes the QR code, intermediate status, and the final admin-friendly PDF directly to the user via Feishu:

```bash
python3 /root/full_qcc_review.py "<contract_file_path>"
```

This script: launches Chrome → screenshots the QCC QR and sends it to Feishu → polls for login (auto-refreshes QR on expiry, re-pushes new QR) → searches the company → extracts registry fields → runs run_contract_review.py with --company-check → generates a clean admin-friendly PDF (single file output: `合同审核报告_行政版.pdf`) → pushes ONLY this PDF to Feishu. The user receives just one polished PDF, no markdown / excel / json clutter.

If Party A name cannot be extracted from the contract, pass `--company-name "<name>"`.

Do not use the legacy qcc_contract_review_demo.py when running through IM — it does not push the QR to chat.


This is the only default skill for the contract-review package. The Python modules handle document loading, field extraction, rule checking, and report writing. Do not look for separate skills for these steps.

When the user gives a contract path in a simple prompt such as `请帮我审核这个合同，<contract_file_path>`, run the QCC-assisted wrapper by default:

```bash
python3 /root/full_qcc_review.py "<contract_file_path>"
```

This default tries to reuse the saved local QCC browser session. If no valid session exists, it opens the QCC QR-login window. If QCC login, captcha, access restriction, or extraction failure prevents usable company evidence, the wrapper still runs the normal contract review and must clearly say that company verification was not completed.

Supported contract inputs are `.docx`, `.pdf`, and `.txt`; `.docx` is preferred. The reviewer reads Word body text, tables, highlights, and `word/comments.xml` comments when available.

Typical user prompts:

- `帮我审核一下这个文件：<合同文件完整路径>`
- `请审核这个合同 <合同文件完整路径>`
- `请帮我审核这个合同，<合同文件完整路径>`
- `看一下这个横向合同有没有问题 <合同文件完整路径>`

For these simple prompts:

1. Extract the contract file path.
2. Run `python3 /root/full_qcc_review.py "<contract_file_path>"`.
3. **STOP.** The script pushes the admin-friendly PDF to Feishu by itself. Your final IM reply must be at most ONE short sentence such as `审核完成，行政版PDF已推送。`. Do NOT summarize findings, do NOT list rule IDs, do NOT paste tables. The PDF IS the deliverable.
4. Do NOT read `contract_review.md` / `contract_findings_*.json` to compose a summary. The user explicitly does not want chat-text summaries.

Do not manually summarize the contract without running the script. Do not ask the user for command-line details when a valid file path is already present.

**Critical rule: ALWAYS use `python3 /root/full_qcc_review.py "<path>"` for every contract-review request, even when:**
- the user says `只做本地审核` / `不查企查查` / `离线审核` — the wrapper auto-detects this state, skips QCC, and still produces the proper admin PDF in `output/im_review/<timestamp>/`.
- 企查查 returns captcha / 405 / 403 / rate limit — the wrapper handles fallback internally.
- Feishu credentials are missing (`[config] Feishu APP_ID/...`) — the wrapper degrades gracefully and prints `[fs_text(disabled)]` lines locally; openclaw-gateway delivers the PDF.

**Never invoke `python /root/contract-review-openclaw-portable/run_contract_review.py` directly.** That bypasses QCC, the admin PDF generator, the timestamped output dir, and produces inferior chat output. The only correct entry point is `full_qcc_review.py`.

## Company Registry Checks

QCC-assisted verification is built into `full_qcc_review.py`. 企查查 may trigger login, captcha, 405/403 security blocks, or rate limits; the wrapper handles all of these internally and degrades to a rule-only review when needed. **You do not need to call any other script for the QCC phase.**

Company information may be used only from controlled sources:

- QCC evidence captured by `full_qcc_review.py` during this run.
- A prepared company-check file provided by the user.
- Screenshots, copied page text, or a manual registry record provided by the user.

- If the user provides a prepared company-check JSON, pre-stage it and let `full_qcc_review.py` pick it up via `--company-name <name>` (the wrapper will skip QCC re-fetch when a stub draft already exists). If you must run the legacy reviewer directly with a prepared draft (rare), use:

```bash
# Legacy / advanced path only — prefer full_qcc_review.py
python "/root/contract-review-openclaw-portable/run_contract_review.py" "<contract_file_path>" --company-check "<company_check_file>"
```

- If the user provides 企查查 screenshots, copied page text, or a manual registry record, extract only the visible/provided fields and treat missing fields as unknown.
- If QCC/company evidence is unavailable, still complete the contract review (the wrapper does this automatically). In the final response, note that external company verification was not completed and that 企查查截图或人工核验记录 should be supplied if needed.

Never use model memory, general knowledge, or "publicly known" facts to fill company registry fields.

## Explicit QCC-Assisted Contract Review

Only use this workflow when the user explicitly asks to use 企查查扫码登录/企查查核验 to verify the counterparty for a contract, and the prompt includes a contract file path.

Run the integrated wrapper which pushes QR + report to Feishu (this is the ONLY supported way to run QCC-assisted review):

```bash
python3 /root/full_qcc_review.py "<contract_file_path>"
```

The wrapper handles login state reuse, QR push to Feishu, company search, field extraction, contract review, and final admin-friendly PDF push.

The legacy script `demos/qcc_contract_review_demo.py` MUST NOT be invoked under any circumstance — it does not push the QR to chat and produces no admin PDF.

Behavior:

- Extract Party A company name from the contract.
- Open a visible local QCC browser window and wait up to 900 seconds for the user to scan the QR code.
- When `--reuse-profile` is used, first check the saved local browser profile. If an existing QCC login session is still valid, skip the QR scan and continue to company verification.
- Search only that single Party A company, and only after QR login is detected.
- Save visible-page evidence, a dashboard-friendly HTML preview page, and a draft `company_check` file under `output/qcc_login_demo/`.
- Rerun the contract review with the generated `company_check` file when it contains usable fields.
- If login timeout, captcha, access restrictions, or insufficient fields prevent usable extraction, still run the normal contract review and say the company verification was not completed.

The dependency is linear and strict:

1. QR page captured.
2. User scans QR and login is detected.
3. Company search starts.
4. Company evidence is captured.
5. Contract review reruns with company evidence.

Never skip from step 1 to step 3. If step 2 fails or times out, do not search QCC and do not claim company verification was completed.

Session reuse notes:

- The saved session lives under `.browser-profiles/qcc-demo` in the local project folder.
- It stores normal browser cookies/local session data, not a password managed by this package.
- It may expire or be invalidated by QCC at any time; then the browser will ask for QR login again.
- Do not include `.browser-profiles/` in portable packages or cloud handoff artifacts.
- To clear the saved login state, delete `.browser-profiles/qcc-demo`.

In the final response, clearly state whether the company verification material was actually used in the review, and provide the local preview page path `output/qcc_login_demo/qcc_login_demo_latest.html` when QCC was opened. Do not say A1/A2/A3 or any rule ID. Use plain wording such as:

- `本次已使用企查查可见页面生成的企业核验草稿重新审核。`
- `本次只完成二维码登录测试，未形成可用于审核的企业核验材料。`

## Explicit QCC QR-Login Demo

Only run this demo when the user explicitly asks to test QCC QR login, show a QCC login QR code, pop up a QCC login browser, or use similar wording such as `企查查二维码`, `企查查扫码登录`, `弹出二维码`.

For dashboard testing, run:

```bash
python "/root/contract-review-openclaw-portable/demos/qcc_login_demo.py" "华为技术有限公司" --login-only --hold-seconds 900
```

If the user gives another company name, replace `华为技术有限公司` with that name. If the user asks for a shorter hold time, use the requested number of seconds.

Expected behavior:

- A visible local browser window opens to QCC login.
- A QR-login screenshot is saved under `output/qcc_login_demo/`.
- A run record is saved as `output/qcc_login_demo/qcc_login_demo_latest.md` and `output/qcc_login_demo/qcc_login_demo_latest.json`.
- A local HTML preview page is saved as `output/qcc_login_demo/qcc_login_demo_latest.html`; it embeds the screenshot so the dashboard can point the teacher to one file instead of only showing a raw PNG path.
- The browser remains open for `--hold-seconds`; use 900 seconds by default to allow local or cloud latency.
- If OpenClaw accidentally omits `--hold-seconds`, the script default is still 900 seconds. Earlier versions closed quickly because `--login-only` had a zero-second hold by default; do not rely on that old behavior.
- Reply with the preview HTML path first, then the screenshot path and latest run-record path. Say that the dashboard chat bubble may show paths rather than inline images, and that this is only a login demo and does not mean company verification is complete.

Do not continue to query company information unless the user explicitly asks to continue after scanning. Do not bypass captcha, WAF, paywalls, paid fields, or access restrictions.

## Cloud ArkClaw / Feishu Handoff

This local package does not implement Feishu or DingTalk sending. In cloud ArkClaw, use the platform connector to send outputs produced by this package:

- `output/qcc_login_demo/qcc_login_demo_latest.json`: manifest with status, result screenshot path, preview HTML path, and draft company-check path.
- `output/qcc_login_demo/qcc_result_*.png`: QCC result screenshot for upload.
- `output/contract_review.md`: administrative review report.
- `output/合同形式化审核总表.xlsx`: spreadsheet summary.

Prefer sending the review summary, Markdown report, Excel file, and QCC result screenshot. Do not send QR-login screenshots to group chats unless the user explicitly asks for a controlled login test.

## Internal Review Pipeline

The script pipeline is:

1. `scripts/contract_loader.py`: load `.docx/.pdf/.txt`, including Word comments and highlights where possible.
2. `scripts/contract_extractor.py`: extract contract fields and evidence snippets.
   It now also calls `scripts/template_matcher.py`, which compares the contract
   against `references/templates/*.docx` (中山大学科研合同范本). If the contract
   is based on a school template, the result `template_match` reports per-clause
   status (unchanged / modified / rewritten / added / removed) and is rendered
   as section "三、学校范本对照" in the admin PDF.
3. `scripts/contract_rule_checker.py`: apply `references/rules/horizontal_contract_formal_rules.yaml`.
4. `scripts/contract_report_writer.py`: write Markdown, JSON, and Excel outputs to `output/`.

The rule engine distinguishes:

- `enforce`: automatically checkable risk items.
- `review`: items that require human confirmation.
- `not_checked`: retained for record only; these must not be counted as risk findings.

## Final Response Rules

After running the script, read the generated `contract_findings_<hash>.json`. Any count in the natural-language final answer must come from `summary_stats`; do not recount items from Markdown or by visual inspection.

The final answer is for administrative staff. Do not expose technical terms such as:

- `JSON`
- `summary_stats`
- `findings`
- `enforce`
- `review`
- `not_checked`
- `schema`
- `python`
- command line / stdout / stderr
- rule IDs such as `A1`, `D1`, `E9`

Recommended Chinese final structure:

1. `审核结论`: 2-4 sentences in plain Chinese. Explain whether it can be submitted after modification, whether materials are missing, and whether company verification was used.
2. `建议先修改的事项`: use a Markdown table, not a loose bullet list. Columns: `序号 | 问题 | 关联条款/证据 | 建议处理`.
3. `需要人工确认或补充材料的事项`: use a Markdown table with the same columns.
4. `企业信息核验情况`: short paragraph plus visible key fields if available, such as company name, credit code, legal representative, registered address, and status.
5. `知识产权重点`: when relevant, distinguish project-generated IP ownership from background IP ownership and background IP use arrangements.
6. `报告位置`: provide only the Markdown report path and Excel summary path.

For the two issue tables:

- Each issue must connect the problem to a specific contract clause, evidence snippet, or external-verification evidence.
- Prefer the generated Markdown report's `行政摘要` tables and the review output fields `title`, `message`, `location`, `evidence`, and `suggestion`.
- Keep each table row concise enough for an administrative teacher to scan.
- Do not show rule IDs unless the user explicitly asks for technical details.

## Intellectual Property Summary

When an IP finding is present, use the structured details from the review output and distinguish:

- Project-generated results / IP ownership: who owns the IP created under this contract.
- Background IP ownership: pre-existing IP remains owned by the original owner unless clearly transferred.
- Background IP use arrangement: whether the counterparty, affiliates, or third parties may use or implement the university team's background IP, and whether scope, duration, parties, and fees need review.

Do not collapse background-IP use authorization into "all IP belongs to Party A". These are legally different points and must be summarized separately.
