# 2026-05-11 行政版报告与 QCC 流程修复

本次会话对**合同审核飞书机器人**与**openclaw-portable**两个 repo 做了一组关联修复，主要解决：

1. 行政版 PDF（v6）的 6 项瑕疵 → 升级到 v8 全绿
2. 企查查（QCC）限流页被误判为「登录失效」、错误推送首页截图

> 两个 repo 同源（`liangch97/verifyAgent.git`），分支不同：
> - `contract-review-feishu-bot` 分支（IM 入口、PDF 渲染）
> - `main` 分支（openclaw-portable，规则引擎/QCC demo）

---

## 一、行政版 PDF 修复（v6 → v8）

针对 `合同审核报告_行政版(6).pdf` 的 6 项瑕疵：

| 编号 | 严重度 | 问题 | 修复 |
|---|---|---|---|
| P0-1 | 高 | 「统一信用代码」未回填 QCC 抓取数据 | `admin_report.py` 增加 `merged_basic_info(company_check=...)` 回填路径，QCC 抓到即覆盖文档抽取空值 |
| P0-2 | 高 | 「履行起止：None 至 None」直接出现在报告中 | 渲染层 `None` → 中文连字符「—」；同时为 `rule.get("dates")` 加 list/dict 兼容 |
| P0-3 | 高 | 五-1 工商核验把"合同[的，应要求...]"当 legal_rep 与外部"胡俊文"对比 | 过滤无差异条目，仅展示真有差异的核验项 |
| P1-1 | 中 | 「合同期限45年」误识（专利号 `ZL2025102` 字面误匹配） | `contract_rule_checker._check_date_term` 正则收紧到 `(?:有效期限\|合同期限\|协议期限\|履行期限\|合同有效期)\s*[:：为共约 ]{0,4}(?<!\d)(\d{1,2})\s*年(?!\d)` |
| P2-1 | 低 | "(原始文件名编码异常)" 提示不友好 | 修订为提示语+建议 |
| P2-2 | 低 | 范本对照 61 条占 6 页太长 | 新增 ENV `ADMIN_PDF_HIDE_UNCHANGED=1`（默认开），折叠未改动条款，可配置 |

**验证结果**：v8 PDF 7 页，`期限45年=False`、`履行起止 None=False`、`fix=5`、`manual=4`、`已折叠提示=True`、`信用代码=91440105MAK7LDBP4J`。

---

## 二、QCC 流程统一为「人工介入」分支

### 问题诊断

旧 caller 把"未登录"和"限流验证"两种状态分两条路径处理：
- 限流路径：截图当前页 → 推送 → 5 min 轮询
- 未登录路径：navigate `QCC_HOME` → 截图首页 → 推送二维码 → 50s 刷新

`detect_blocked_reason(visible_text)` 在很多情形下走不到（限流页让 `search_company` 抛异常 → caller 拿到 `("", True)` → blocked_reason 为空 → 走"未登录"分支 → 截图首页推送）。**用户看到的永远不是真实状态**。

### 修复

1. **`try_search()` 异常分支**：改成"必先抓 visible_text 再返回"，让 caller 能识别限流（`full_qcc_review.py`）。
2. **caller 三段并一段**：删除 QR 截图/刷新/二维码失效检测/限流截图等所有分支，统一为：
   - 推送 1 条文本：`⏸️ 企查查环节需要人工介入`
   - **不导航、不截图**（保留 Chrome 当前页面，操作者自己看）
   - 8 秒轮询，最长 5 min；每 60s 推送进度
   - 超时回落 stub draft（`source=skipped_qcc_manual_timeout`）→ 仅规则审核

### 影响

- 限流页（"操作过于频繁，验证一下"）、登录失效、其它弹窗，全部走同一条路径
- 不再让用户对着首页截图困惑
- 飞书消息体积下降（去掉了二维码/限流图）

---

## 三、变更文件

### `contract-review-feishu-bot` 分支

| 文件 | 摘要 |
|---|---|
| `admin_report.py` | P0-1/P0-2/P0-3/P2-1/P2-2 全部修复；ENV 折叠未改动条款 |
| `full_qcc_review.py` | QCC 分支统一为人工介入；`try_search` 异常时抓页面文本 |
| `scripts/template_matcher.py` | 阈值 0.45→0.40（历史调整一并提交） |
| `skills/contract-formal-review-flow/SKILL.md` | 历史调整一并提交 |

### `main` 分支（contract-review-openclaw-portable）

| 文件 | 摘要 |
|---|---|
| `scripts/contract_rule_checker.py` | `_check_date_term` 收紧正则修 P1-1 |
| `demos/qcc_login_demo.py` | `BLOCK_KEYWORDS` 含「操作过于频繁/验证后再操作/验证一下」；`is_qcc_login_page` 加 logged_in_markers 白名单 |
| `scripts/template_matcher.py` | 历史 SYSU anchor / preamble terminator 删除一并提交 |
| `skills/contract-formal-review-flow/skill.txt` | 历史新增一并提交 |

---

## 四、运行/部署注意

- 网关：`/root/openclaw_gateway` 双 fork daemon，pid=717 listening 18789（未变更）
- WSL 部署目录：`/root/full_qcc_review.py`、`/root/admin_report.py`、`/root/contract-review-openclaw-portable/`
- 备份：每次 patch 都留 `.bak6`/`.bak_simplify` 等同名备份在原目录
- 环境变量新增：`ADMIN_PDF_HIDE_UNCHANGED`（默认 `1`，设为 `0` 可关闭折叠）
