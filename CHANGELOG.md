# 更新日志

> 本文件记录 `contract-review-openclaw-portable` 包的对外可见改动。
> 时间倒序，最近改动在最上方。

## [2026-05-07] 范式合同形式化审查 skill 嵌入与主 skill 解耦

### 背景

OpenClaw 上原本只有一个 `contract-formal-review-flow` skill，承载完整的横向合同形式化审核流程；为支持「这个合同是不是基于学校范本？修改了哪些条款？」一类问题，新增了基于 `scripts/template_matcher.py` 的范本对照能力。

直接把范本对照说明塞进原 skill 后，`SKILL.md` 体量超过 22KB / 277 行，OpenClaw 模型对 skill 的把握能力下降——会忽略范本对照、混淆 IM 模式回复结构。本次改动按 Anthropic Skills 的「单一职责 + 渐进披露」原则把范本对照拆为独立 skill，并把主 skill 的长篇手册外移到 `references/`。

### Skills

- 新增 **`skills/contract-template-compliance/SKILL.md`**：范本对照专用 skill。
  - 触发词：`范本 / 范式 / 示范文本 / 学校范本 / 中大范本 / 范本对照 / 模板对照 / 条款偏离 / template compliance / clause deviation`。
  - 不重复执行任何脚本，只读取主流程已写入 JSON 的 `template_match` 字段。
  - 明确规定三种决策路径（`matched=False` / `modified_count=0` / `modified_count>0`）以及对应的中文回复结构。
  - 内置正反例参考路径，模型可直接照搬措辞，无需自行推断。
- **`skills/contract-formal-review-flow/SKILL.md`** 精简至 11.4KB / 214 行（降幅 48%）：
  - 保留：强制执行规则、IM 飞书模式、最终回复结构、知识产权摘要规则——既有飞书行为不变。
  - 外移：QCC QR-login demo / Cloud ArkClaw handoff / 浏览器会话复用细节，搬到 `references/handoff/qcc_and_arkclaw.md`。
  - 末尾新增「学校范本对照（范式合同审核）」一节，明确把范本相关问题路由到新 skill。
  - YAML `description` 改为双引号字符串，规避 `: ` 触发的 mapping 歧义。
- 新增 **`references/handoff/qcc_and_arkclaw.md`**：从主 SKILL.md 外移的 QCC / ArkClaw / 飞书连接器长篇手册。

### 匹配器（`scripts/template_matcher.py`）

为避免误把行业自拟合同识别为「学校范本」（典型反例：乙方为中山大学的国家科技部技术服务示范文本合同），把单一形状相似度判定升级为**形状 + 内容双门槛**：

- 默认 `match_threshold` 由 `0.40` / `0.45` 抬高到 **`0.65`**。
- 新增 SYSU 专属锚点短语清单（`【科学研究院】` / `【科研管理部门】` / `学校合同管理信息系统` / `中山大学·深圳` 等）：
  - 通用词 `中山大学` / `示范文本` / `中大` 一律剔除——它们会出现在乙方为中大的国家科技部范本里，无判别力。
  - `anchor_min` 默认 1，必须命中至少 1 项专属短语才认定为基于学校范本。
- 新增 `_strip_preamble`：丢弃首条 `第一条` 之前的「使用说明」段（`一、二、三、…`），消除负样本上凭空冒出的 `removed` / `added` 噪声。
- 输出新增字段：`anchor_hits` / `anchor_min` / `match_threshold`，并把 `reason` 改写为更可读的形式（如 `non_template_contract: similarity_0.41<0.65 and anchors_0<1`）。

### 流水线

- `scripts/contract_extractor.py`
  - `HEADING_RE` 兼容更多条款标号（`一、` / `（一）` / `第一部分` / 阿拉伯数字编号）。
  - `_PARTY_ROLE_ALIASES` 增加 `委托方/受托方/转让方/受让方/合作方/服务方/需求方/供方` 等同义词，配合 `_extract_party_name(text, "甲" / "乙")` 抽取更稳健。
  - 提取结果新增 `template_match`（`_detect_template_match_safe` 包装，匹配器异常时返回 `error` 而不抛出）。
- `scripts/run_contract_review.py`
  - 引入 `detect_template_match`，把 `template_match` 同时挂到 `extracted` 和 `review`，确保 admin PDF 的「三、学校范本对照」与下游 skill 都拿得到。

### 验证

`run_contract_review.py` 真实流水线在两个样本上的回归结论：

| 案例 | matched | similarity | anchor_hits | 决策 |
|---|---|---|---|---|
| 反例 `samples/sysu/PCDW_neg.docx`（行业自拟，乙方为中山大学） | False | 0.41 | 0 | 渲染「本合同不是基于中山大学合同范本起草」 |
| 正例 `samples/sysu/zhuanli_pos.docx`（基于专利转让范本） | True | 0.95 | 5 | 渲染「基于学校范本《中山大学专利技术转让合同》……未改动 38 / 修改 9 / 改写 5 / 新增 2 / 删除 7」 |

YAML 前置元数据通过解析校验：两个 SKILL.md 的 `description` 长度分别为 629 / 559 字符（在 Anthropic Skills 推荐的 1024 字符以内）。

### 部署提示

- WSL 上的 OpenClaw skill 目录：`~/.openclaw/skills/`。本次新增 `contract-template-compliance/`、改写 `contract-formal-review-flow/`。
- 旧的整段 `contract-formal-review-flow/SKILL.md` 已就地备份为 `SKILL.md.preTemplateSplit.bak`，需要回滚时直接覆盖即可。
- 范本文件位置不变：`references/templates/中山大学*.docx`；新增范本时复制 `.docx` 到该目录即可，匹配器在第一次调用时会缓存。
