# Contract Review Feishu Bot

基于 [OpenClaw](https://github.com/cline-labs/openclaw) 的合同形式化审核机器人，飞书 IM 端到端：

- 用户在飞书直接 **发送合同文件**（`.docx` / `.pdf`）或附文字「审核这个」
- 机器人自动调用脚本：启动 Chromium → 推送企查查二维码到飞书 → 等待扫码登录 → 抓取甲方工商信息（15 字段）→ 跑合同条款规则引擎 → 推送 **行政版 PDF** 到飞书
- 仅一句话回复 + 一份 PDF，无多余文字摘要

> ⚠️ 这是单用户、单租户的内部工具，App ID / App Secret / User Open ID 通过本地 config.json 注入，不进入仓库。

---

## 仓库结构

```
contract-review-feishu-bot/
├── README.md                                   # 本文件
├── DEPLOYMENT.md                               # 完整部署步骤（Linux/WSL + 飞书）
├── requirements.txt
├── full_qcc_review.py                          # 主管线脚本（飞书 ↔ QCC ↔ 合同规则）
├── admin_report.py                             # 行政版 PDF 渲染器
├── skills/
│   └── contract-formal-review-flow/
│       └── SKILL.md                            # OpenClaw 技能（v5：含文件上传触发）
└── scripts/
    └── qcc_login_demo.py                       # 企查查登录 + 抓取（v2 多字段抽取）
```

## 快速开始

1. 部署 OpenClaw + 飞书机器人 → 见 [DEPLOYMENT.md](DEPLOYMENT.md)
2. 安装本仓库：
   ```bash
   git clone https://github.com/liangch97/contract-review-feishu-bot.git ~/contract-review-feishu-bot
   cd ~/contract-review-feishu-bot
   pip install -r requirements.txt
   ```
3. 写入飞书配置 `~/.config/contract-review-feishu-bot/config.json`（见 DEPLOYMENT.md）
4. 把 SKILL.md 拷到 OpenClaw 技能目录、把 `full_qcc_review.py` / `admin_report.py` 链到 `/root/`，把改好的 `qcc_login_demo.py` 替换到 OpenClaw portable 包里：
   ```bash
   bash install.sh
   ```
5. 在飞书机器人聊天里上传一份合同 docx，附文字 `审核这个`，等待行政版 PDF 推送

## 触发方式

| 飞书消息 | 行为 |
|---------|------|
| `请帮我审核这个合同：/path/to/contract.docx` | 用绝对路径触发 |
| 上传 `.docx` 附件 + 文字 `审核这个` | 自动以附件路径触发 |
| 仅上传附件、无文字 | 同样自动触发（agent 识别 `<media:document>` 占位） |

## 已知问题

- OpenClaw 2026.4.26 + MiniMax provider：`/new` 命令可能产生空 prompt 导致 `messages must not be empty (2013)`。**绕过方式**：直接发新指令，无需 `/new`；如需彻底清空，归档 `~/.openclaw/agents/main/sessions/*.jsonl` 后重启 gateway。
- 企查查页面布局变更可能导致字段抓不全。`scripts/qcc_login_demo.py` v2 解析器同时兼容「label：value 同行」与「label 一行 / value 下一行」两种格式。
