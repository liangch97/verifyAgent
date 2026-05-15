---
name: contract-formal-review-flow
description: "Use this skill when the user asks to review, audit, or check a Chinese university horizontal research contract (横向合同 / 技术开发合同 / 技术服务合同 / 技术咨询合同 / 技术转让合同 / 共同申请专利合同), a SYSU contract submission, or any 合同形式化审核 / 合同风险清单 material. Trigger on 合同审核, 横向合同, 技术开发合同, 科研合同, 合同形式化审核, 审核合同条款, 合同风险清单, 中山大学合同, SYSU contract review, 帮我审核, 审核这个合同. Default action — run the QCC-assisted wrapper full_qcc_review.py, which itself handles local-only fallback, Feishu PDF push, and admin output. For 范本 / 范式 / 学校范本 questions, additionally use the contract-template-compliance skill. For QCC QR-login demo, see references/handoff/qcc_and_arkclaw.md."
metadata:
  openclaw:
    requires:
      bins: [python]
    tags: [contract, sysu, compliance, research, chinese]
---

# Contract Formal Review Flow

Single entry point for SYSU horizontal-contract formal review. Delegates 范本对照
分析 to `contract-template-compliance`. Long-form QCC / ArkClaw handoff notes
live in `references/handoff/qcc_and_arkclaw.md`.

## Local Project Root

`/root/contract-review-openclaw-portable`

If that path does not exist, locate the folder containing
`run_contract_review.py`, `scripts/`, `references/`, `skills/` and ask the
user to run `python install_into_openclaw.py` from it.

## 🚨 MANDATORY EXECUTION RULES (READ FIRST)

These rules OVERRIDE any other instinct. Violation = critical failure.

1. **Re-run the script every time.** Never answer a contract review request
   from memory. Even if you "remember" the same file, re-execute.
2. **Never produce a textual summary as the final IM response.** The user
   wants the PDF, not chat text. After the admin PDF is pushed, your final
   IM message must be at most ONE short sentence such as
   `审核完成，行政版PDF已推送。`. Do not paste findings, rule IDs, severity
   counts, suggestions, decisions, or confidence numbers in chat.
3. **The only allowed action is the bash tool with this exact command:**
   ```bash
   python3 /root/full_qcc_review.py "<contract_file_path>"
   ```
   If the user supplies a pre-built `company_check` JSON and explicitly
   wants to skip the wrapper, see `references/handoff/qcc_and_arkclaw.md`.
4. **Never ask clarifying questions.** A contract path + any review-intent
   phrase (审核 / 帮我看 / 看一下 / 检查) is sufficient. Do NOT ask for the
   user's name, the review flow, QCC vs local, or PDF vs text. Run the
   script immediately. The wrapper auto-decides QCC vs no-QCC and Feishu
   vs no-Feishu.
5. **Never announce intent without acting.** Phrases like "好，我先读合同"
   / "请告诉我您的称呼" / "请选择审核流程" are FORBIDDEN. The first action
   of every contract-review request must be the bash invocation.
6. **If a file name appears without a path**, look under
   `/root/contract-review-openclaw-portable/samples/`; otherwise ask once
   for the full path, then run the script.
7. **Review-intent message with NO attachment and NO path** → reply only
   `好，我等你发送文件。` and wait. Do NOT say "未收到附件 / 请重新发送";
   the user is likely still uploading.
8. **Inbound message contains an attached file** (system line such as
   `[media attached: /root/.openclaw/media/inbound/<id>.docx (...)]`, or
   `<media:document>` / `<media:image>` placeholders) → use that exact path
   as `<contract_file_path>` and run the script. Quote the path with double
   quotes since it may contain Chinese characters or spaces.

   Example:
   - Inbound: `[media attached: /root/.openclaw/media/inbound/abc123.docx (...)]\n\n审核这个`
     → Run: `python3 /root/full_qcc_review.py "/root/.openclaw/media/inbound/abc123.docx"`

## ❌ FORBIDDEN RESPONSES

| Bad response | Why it's wrong |
|---|---|
| `好，先读合同，同时快速确认两件事：你是？这篇合同走哪个审核流程？` | Asks for user name and flow |
| `请问您希望走企查查核验还是仅本地审核？` | Asks for review mode |
| `先读起来了，稍后给您结果` | Announces intent without invoking the tool |
| `请告诉我合同的项目名称和金额` | Re-asks info already in the file |
| `根据合同内容，我建议关注以下几点……` | Textual summary instead of PDF |
| Sending the PDF via gateway after the script already pushed it | Causes duplicate file in Feishu |
| `未收到附件，请重新发送合同文件。` after script success | Script already succeeded; extra messages confuse the user |
| `没有看到附件，请提供文件路径或重新发送附件。` | User may still be uploading; say `好，我等你发送文件。` instead |

After successfully invoking the script and seeing the wrapper's
`[fs_pdf]` / `[delivery]` confirmation:

1. Wait for completion.
2. Reply with one sentence (e.g. `审核完成，行政版PDF已推送。`).
3. **STOP COMPLETELY.** Do not send additional messages, do not re-evaluate
   the original user message, do not say "未收到附件" or ask the user to
   resend. The task is finished — emit nothing further.

## ⚡ IM-Driven Mode (Feishu)

When triggered through Feishu IM, ALWAYS run:

```bash
python3 /root/full_qcc_review.py "<contract_file_path>"
```

This script pushes the QR (if needed), intermediate status, and the final
admin-friendly PDF directly to the user via Feishu. The user receives one
polished PDF — `合同审核报告_行政版.pdf` — no markdown / Excel / JSON clutter.

If Party A name cannot be extracted, pass `--company-name "<name>"`.

The wrapper handles all of these conditions internally:

- User says `只做本地审核` / `不查企查查` / `离线审核` → wrapper auto-detects,
  skips QCC, still produces the proper admin PDF in
  `output/im_review/<timestamp>/`.
- 企查查 returns captcha / 405 / 403 / rate limit → wrapper falls back.
- Feishu credentials missing → wrapper degrades gracefully and prints
  `[fs_text(disabled)]`; openclaw-gateway delivers the PDF.

**Never invoke `python /root/contract-review-openclaw-portable/run_contract_review.py`
directly from a contract-review request.** That bypasses QCC, the admin
PDF generator, and the timestamped output dir. The only correct entry
point is `full_qcc_review.py`.

## Internal Pipeline (read-only reference)

`full_qcc_review.py` orchestrates these scripts and you should not call them
individually:

1. `scripts/contract_loader.py` — load `.docx/.pdf/.txt` (body, tables,
   highlights, `word/comments.xml`).
2. `scripts/contract_extractor.py` — extract structured fields and
   evidence. **Also calls `scripts/template_matcher.py`** to detect whether
   the contract is based on a SYSU template; result lands in
   `template_match` (handed off to the `contract-template-compliance` skill).
3. `scripts/contract_rule_checker.py` — apply
   `references/rules/horizontal_contract_formal_rules.yaml`. Severity:
   - `enforce` — automatically checkable risk items.
   - `review` — items that require human confirmation.
   - `not_checked` — record-only, must NOT count as risk findings.
4. `scripts/contract_report_writer.py` — write Markdown / JSON / Excel.

## Final Response Rules

After running the script, read the generated `contract_findings_<hash>.json`.
Any count in the natural-language final answer must come from
`summary_stats`. Do not recount items from Markdown or by visual inspection.

The final answer is for administrative staff. Do NOT expose technical
terms: `JSON`, `summary_stats`, `findings`, `enforce`, `review`,
`not_checked`, `schema`, `python`, command line, stdout/stderr, rule IDs
such as `A1`/`D1`/`E9`.

Recommended Chinese final structure (only when the user explicitly asks
for a chat summary AND the IM PDF path is not in use):

1. **审核结论** — 2-4 sentences in plain Chinese: can-submit /
   submit-after-modification / needs-materials, plus whether company
   verification was used.
2. **建议先修改的事项** — Markdown table, columns:
   `序号 | 问题 | 关联条款/证据 | 建议处理`.
3. **需要人工确认或补充材料的事项** — same Markdown table format.
4. **企业信息核验情况** — short paragraph plus visible key fields if
   available (name, credit code, legal rep, registered address, status).
5. **知识产权重点** — when relevant, distinguish project-generated IP
   ownership from background IP ownership and background IP use
   arrangements.
6. **学校范本对照** — one sentence read from `template_match`. Detailed
   per-clause deviation table is the responsibility of the
   `contract-template-compliance` skill; do not repeat it here.
7. **报告位置** — Markdown report path and Excel summary path only.

For both issue tables: each row must connect the problem to a specific
contract clause, evidence snippet, or external-verification evidence. Use
the review output fields `title`, `message`, `location`, `evidence`,
`suggestion`. Keep rows scannable. Do not show rule IDs unless the user
explicitly asks for technical details.

## Intellectual Property Summary

When an IP finding is present, distinguish:

- **Project-generated IP ownership** — who owns the IP created under this
  contract.
- **Background IP ownership** — pre-existing IP remains owned by the
  original owner unless clearly transferred.
- **Background IP use arrangement** — whether the counterparty / its
  affiliates / third parties may use or implement the university team's
  background IP, and whether scope, duration, parties, and fees need
  review.

Do not collapse background-IP use authorization into "all IP belongs to
Party A". These are legally different points and must be summarized
separately.

## 学校范本对照（范式合同审核）

When the user's request includes 范本 / 范式 / 示范文本 / 学校范本 / 中大范本
/ 范本对照 / 模板对照 / 条款偏离, additionally activate the
**`contract-template-compliance`** skill. Its sole responsibility is to
read the `template_match` block from the JSON that this flow already
produces, decide 基于范本 vs 自拟合同, and render the per-clause deviation
table. Do not duplicate that logic here.

The two reference cases for `contract-template-compliance`:

- **正例**：`samples/sysu/zhuanli_pos.docx`（即 `附件3_附件3：技术转让（专利权）合同.docx`）
  → `template_match.matched=True`，识别为「中山大学专利技术转让合同.docx」。
- **反例**：`samples/sysu/PCDW_neg.docx`（即 `PCDW弯道偏离预警...合同.docx`）
  → `template_match.matched=False`，使用的是国家科技部技术服务示范文本，
  乙方虽为中山大学，但合同非基于学校范本起草。

## Long-form QCC and ArkClaw notes

See `references/handoff/qcc_and_arkclaw.md` for:

- QCC verification details and whitelist of company evidence sources.
- Cloud ArkClaw / Feishu connector output list.
- Explicit QCC QR-login demo command (`demos/qcc_login_demo.py`).
- Saved login session location and clearing instructions.

These are intentionally moved out of this SKILL.md to keep the active
context focused on the formal-review flow.
