---
name: contract-template-compliance
description: "Use this skill when the user asks whether a contract is based on a 中山大学 official 合同范本 / 范式合同 / 示范文本, when they want a 学校范本对照 / 范本符合性审核 / 条款偏离分析 / 范本差异点, or when they say things like '这个合同是不是用了学校的范本?' '对照学校范本看看修改了哪些条款' '这是范式合同吗' '和中大的合同模板有差别吗'. Trigger on 范本 / 范式 / 示范文本 / 学校范本 / 中大范本 / 中山大学范本 / 模板对照 / 范本对照 / 条款偏离 / template compliance / clause deviation. The skill reads the existing template_match block produced by full_qcc_review.py / run_contract_review.py, decides 基于范本 vs 自拟合同, and reports per-clause deviations against references/templates/中山大学*.docx."
---

# contract-template-compliance

This skill is the 范本对照 / 范式合同 specialist. It does **not** run a separate command — it reads the `template_match` field that the standard reviewer (`full_qcc_review.py`) already writes into `contract_findings_<hash>.json` and produces a focused, administrator-friendly answer.

## When to activate

Activate **in addition to** `contract-formal-review-flow` whenever the user's intent includes any of:

- 这是不是用了学校范本 / 是范式合同吗 / 是不是中大模板
- 对照学校范本 / 范本对照 / 模板对照 / 条款偏离
- 范本差异点 / 改了哪些条款 / 与范本相比有什么不同
- 范式合同形式化审查 / 范本符合性审核

Do **not** activate this skill when the user only says 帮我审核这个合同 without referencing 范本/范式 — in that case `contract-formal-review-flow` already covers the standard formal review and includes a brief 范本对照 paragraph at the end.

## How to use the result

The reviewer always populates one of these shapes inside `contract_findings_<hash>.json` and the in-memory review object:

```json
"template_match": {
  "matched": true | false,
  "template_name": "中山大学专利技术转让合同.docx",
  "similarity": 0.95,
  "anchor_hits": 5,
  "anchor_min": 1,
  "match_threshold": 0.65,
  "templates_considered": [...],
  "reason": "non_template_contract: similarity_0.56<0.65 and anchors_0<1",  // only when matched=false
  "clauses": [ {"id": "第一条", "title": "...", "status": "unchanged|modified|rewritten|added|removed", "diff_ratio": 0.95, "template_excerpt": "...", "contract_excerpt": "..."}, ... ],
  "counts": {"unchanged": N, "modified": N, "rewritten": N, "added": N, "removed": N},
  "modified_count": N,
  "summary": "匹配范本：…（相似度 X%，命中范本特征 N 项）；未改动 N 条…"
}
```

### Decision rule

1. **`matched == false`** → 该合同**未基于学校范本**，按通用规则审核即可。在最终回复中明确说一句"该合同不是基于中山大学合同范本起草，已按通用横向合同审核要点审查"，**不要**在回复里列范本条款逐条对照表。
2. **`matched == true` 且 `modified_count == 0`** → 完全沿用范本，未做修改。回复"该合同与学校范本《<template_name>>》一致，无条款偏离。"
3. **`matched == true` 且 `modified_count > 0`** → 这是真正的范式合同审核场景。回复结构见下。

### 正例参考

`/root/contract-review-openclaw-portable/samples/sysu/zhuanli_pos.docx`（即 `附件3_附件3：技术转让（专利权）合同.docx`）应被识别为：

- `matched=True`
- `template_name=中山大学专利技术转让合同.docx`
- `similarity≈1.0`，`anchor_hits>=4`（至少命中 `【科学研究院】`、`学校合同管理信息系统`、`合同管理信息系统`、`中山大学·深圳`）

回复样例首句："本合同基于学校范本《中山大学专利技术转让合同》起草（相似度 100%、命中 5 项范本特征）。"

### 反例参考

`/root/contract-review-openclaw-portable/samples/sysu/PCDW_neg.docx`（即 `PCDW弯道偏离预警功能误触发软件不良分析技术服务合同67500元-合并附件20260224.docx`）应被识别为：

- `matched=False`
- `reason=non_template_contract: similarity_0.56<0.65 and anchors_0<1`
- 它使用的是**国家科技部技术服务合同示范文本**，并且乙方为中山大学（这只说明中大是受托方，并不意味着合同采用了学校范本）

回复样例首句："本合同不是基于中山大学合同范本起草（最相似范本《技术开发（委托）合同-中大为乙方.docx》，整体相似度 56%，未命中学校范本特征短语）。已按通用横向合同审核要点审查。"

## 最终回复结构（matched=True 时）

1. **范本识别**：一句话给出 `template_name`、相似度百分比、`anchor_hits` 数。
2. **整体偏离统计**：用 `counts` 里的数字写一句"未改动 X 条 / 修改 Y 条 / 改写 Z 条 / 新增 A 条 / 删除 B 条"。
3. **重点偏离条款**：从 `clauses` 中筛出 `status in {modified, rewritten, removed, added}` 的条目，按 `diff_ratio` 升序最多取 6 条，做成 Markdown 表：

   | 序号 | 条款 | 偏离类型 | 范本要点 | 合同实际 | 建议关注 |

   - `偏离类型`：用中文标签 `有修改`/`重大改写`/`合同新增`/`范本中存在但合同未见`，不要直接显示英文 status。
   - `范本要点` / `合同实际`：分别取 `template_excerpt`、`contract_excerpt`，每格 ≤80 字。
   - `建议关注`：根据偏离类型给一句操作建议（如"重大改写需复核法务"、"删除条款须确认是否合规"、"新增条款建议法务过审"）。

4. **结论与下一步**：是否可提交、是否需要法务复核、是否需要补材料。

## 数量口径

- 数量字段必须直接读 `template_match.counts` 与 `template_match.modified_count`，**不要**自己重新数 `clauses` 数组。
- `相似度` 用 `template_match.similarity * 100` 取整百分比。
- `命中范本特征 N 项` 直接读 `anchor_hits`。

## 禁止行为

- 不得在 `matched=false` 时列出"范本对照表"或"基于范本的条款偏离"；这种合同根本没有范本基线。
- 不得仅凭乙方是"中山大学"就声称该合同采用了学校范本——`anchor_hits` 才是判定信号。
- 不得把 `template_match.reason` 字段（含 `non_template_contract:` 等英文）原样贴给行政老师；用本文档"反例参考"里的中文措辞改写。
- 不得显示英文 status 名（`unchanged/modified/rewritten/added/removed`），统一映射为中文标签。

## 与 contract-formal-review-flow 的关系

- `contract-formal-review-flow` 调用 `full_qcc_review.py` / `run_contract_review.py` 完成实际运行，并把 `template_match` 写入 JSON。
- 本 skill **不重复运行任何脚本**，只在最终回复阶段读取已经生成的 `template_match` 字段并做范本对照解读。
- 当用户问题同时涉及"通用形式化审核 + 范本对照"时，先按 `contract-formal-review-flow` 的流程跑完审核，再用本 skill 的"最终回复结构"补一段范本对照部分。
