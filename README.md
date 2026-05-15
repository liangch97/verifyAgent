# Contract Review Feishu Migration Package

轻量迁移包：只包含 OpenClaw/飞书合同审核入口脚本、行政版 PDF 渲染器、子 agent 字段复核脚本和两个 skills。不包含飞书凭据、不包含 OpenClaw 本体、不包含 `contract-review-openclaw-portable` 引擎仓库。

## 包内容

- `full_qcc_review.py`：总入口。接收合同路径，复用/人工介入 QCC，调用 portable 审核引擎，生成并推送行政版 PDF。
- `admin_report.py`：行政版 PDF 渲染。默认隐藏子 agent 的技术修正明细；如需调试，设置 `ADMIN_PDF_SHOW_AGENT_DETAIL=1`。
- `agent_review.py`：规则初稿后的子 agent 复核与修正。最多 3 次尝试（首次 + 2 次重试），成功后输出最终字段与内部 corrections。
- `skills/contract-formal-review-flow/SKILL.md`：主审核 skill，约束 agent 收到合同后直接运行入口脚本。
- `skills/contract-template-compliance/SKILL.md`：范本/范式合同对照说明 skill。
- `config.example.json`：本地配置模板，无真实凭据。

## 前置依赖

1. 已安装 OpenClaw CLI，并配置可用模型后端。
2. 已 clone `contract-review-openclaw-portable`，默认路径：`/root/contract-review-openclaw-portable`。
3. 已安装 Chrome/Chromium、Playwright、WeasyPrint 与中文字体（如 Noto Sans CJK SC）。
4. 若需要脚本直接推送飞书消息，准备飞书 `APP_ID`、`APP_SECRET`、`USER_OPEN_ID`。

## 安装

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```

将配置文件放到：

```bash
mkdir -p ~/.config/contract-review-feishu-bot
cp config.example.json ~/.config/contract-review-feishu-bot/config.json
```

然后编辑 `~/.config/contract-review-feishu-bot/config.json` 填入真实值。

也可以用环境变量覆盖：

- `APP_ID`
- `APP_SECRET`
- `USER_OPEN_ID`
- `OPENCLAW_PORTABLE_DIR`
- `OPENCLAW_BIN`
- `ADMIN_PDF_SHOW_AGENT_DETAIL`

## 使用

```bash
python3 full_qcc_review.py "/path/to/contract.docx"
```

如需指定甲方：

```bash
python3 full_qcc_review.py "/path/to/contract.docx" --company-name "广汽本田汽车有限公司"
```

## 字段复核逻辑

当前架构不是旧的“规则 + LLM 双轨合并”。现在是：

1. `scripts.contract_extractor.extract_contract()` 生成规则初稿。
2. `agent_review.review_and_correct()` 把合同全文 + 规则初稿交给 OpenClaw 子 agent。
3. 子 agent 逐字段判断是否合理，不合理就从正文改正，输出唯一最终字段源。
4. 行政版 PDF 默认不展示技术 corrections，避免行政老师困惑。

如果子 agent 连续 3 次失败，脚本会推送告警，并在 PDF 内部状态中标记失败，字段退化为规则初稿，不会静默假装成功。

## 不包含内容

- 不包含飞书真实凭据。
- 不包含 `contract-review-openclaw-portable` 的审核引擎、模板库、QCC demo 代码。
- 不包含 Chrome profile、缓存、输出报告。
