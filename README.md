# contract-review-openclaw

中山大学横向合同形式化审核本地 OpenClaw 包。

> **2026-05 更新**：把范式合同对照拆为独立 skill `contract-template-compliance`；
> 主 skill `contract-formal-review-flow` 精简至 11.4 KB；范本匹配器升级为「形状 +
> 内容」双门槛，详见 [`CHANGELOG.md`](CHANGELOG.md) 和 [`docs/technical_roadmap.pdf`](docs/technical_roadmap.pdf)。

---

## 1. 安装

1. 解压本包到任意目录（或 `git clone` 本仓库）。
2. 在 PowerShell 进入项目根目录。
3. 安装依赖：`pip install -r requirements.txt`
4. 安装 OpenClaw skills：`python install_into_openclaw.py`

`install_into_openclaw.py` 会把 `skills/` 下的 **两个** skill 同步到本机
`~/.openclaw/skills/`：

- `contract-formal-review-flow` —— 形式化审核默认入口。
- `contract-template-compliance` —— 范式合同 / 学校范本对照专用。

换目录或换机器后，请重新跑一次安装脚本（skill 内部会写入当前解压目录路径）。

## 2. 给行政老师的用法

老师只需要对 OpenClaw 说：

```text
请帮我审核这个合同，<合同文件完整路径>
```

OpenClaw 默认会先尝试复用本机企查查登录状态；若登录状态不可用，会弹出企查查二维码让老师扫码。企查查核验成功时，会把甲方企业信息带入合同审核；
若遇到验证码、访问限制、字段不足或登录失败，会自动退回普通合同审核，并在结果里说明企业核验未完成。

示例：

```text
请帮我审核这个合同，<本项目目录>\samples\华为-中大智算集群可靠性测评技术合作协议-脱敏版.docx
```

OpenClaw 应返回行政老师能直接看的结论、修改事项、补材料事项、企业核验情况、知识产权重点和**学校范本对照**结论，以及报告位置。

最终摘要建议采用「简短文字结论 + 表格」的形式。表格应把每个问题和对应合同条款 / 证据放在同一行，便于行政老师逐项转给项目负责人或合作方修改。

### 2.1 范式合同 / 学校范本对照

如果老师想知道「这个合同是不是基于学校范本起草、修改了哪些条款」，可以直接问：

```text
这个合同是不是用了学校的范本？修改了哪些条款？  <合同文件完整路径>
```

或者：

```text
对照学校范本审核：<合同文件完整路径>
```

OpenClaw 会自动激活 `contract-template-compliance` skill，读取主流程已写入
`contract_findings_<hash>.json` 的 `template_match` 字段，并产出三种结论之一：

| 场景 | 含义 | 回复要点 |
|---|---|---|
| `matched=False` | 不是基于学校范本 | 一句话说明，并按通用横向合同规则审核 |
| `matched=True` 且 `modified_count=0` | 完全沿用范本 | 一句话说明无条款偏离 |
| `matched=True` 且 `modified_count>0` | 基于范本但有修改 | 范本名 + 偏离统计 + 重点条款表 |

参考样例：

- 正例：`samples/sysu/zhuanli_pos.docx` —— 基于「中山大学专利技术转让合同」起草。
- 反例：`samples/sysu/PCDW_neg.docx` —— 行业自拟（国家科技部范本，乙方为中山大学）。

## 3. 本地脚本用法

### 3.1 入口选择

| 入口 | 用途 | 何时用 |
|---|---|---|
| `python3 /root/full_qcc_review.py "<合同>"` | **默认入口**：自动 QCC + 飞书 PDF 推送 + 失败回退 | 通过 OpenClaw / 飞书 IM 触发时 |
| `python run_contract_review.py "<合同>"` | 本地审核命令行（不走 QCC，不推飞书） | 命令行调试、批量回归、CI |
| `python run_contract_review.py "<合同>" --company-check "<file>"` | 已有人工整理的企业核验材料 | 老师手工提供企查查截图 / 记录 |

`--company-check` 支持 JSON、CSV、XLSX。没有该文件时，甲方工商信息、关联关系、民用非涉密非军工属性会作为人工复核事项留在报告里。

### 3.2 输出

每次运行都会产出：

- `output/contract_review.md` —— 行政摘要 Markdown。
- `output/contract_findings_<hash>.json` —— 结构化结果，含 `template_match`、`summary_stats`、`findings`。
- `output/合同形式化审核总表.xlsx` —— 行政表格。
- 通过 `full_qcc_review.py` 跑出来的还有 `output/im_review/<timestamp>/合同审核报告_行政版.pdf`（行政老师拿到的最终交付物）。

最终给老师看 PDF（IM 模式）或 Markdown + Excel（命令行模式）即可，不要要求老师理解中间 JSON、schema 或规则编号。

## 4. 企业信息核验

默认提示词会尝试企查查核验甲方企业信息。若企查查登录状态仍有效，会直接查询；若失效，会弹出二维码；若无法形成可用企业核验材料，会退回普通合同审核。

也可以使用人工材料方式：

- 老师提供企查查截图、页面文字或人工核验记录。
- 测试者把材料整理成 `--company-check` 文件。
- 未提供材料时，报告中写明「甲方企业信息未完成外部核验，需补充企查查截图或人工核验记录」。

本包不实现、不支持绕过登录、验证码、付费墙、WAF、反爬策略或访问控制。

详细的 QCC / ArkClaw / 飞书连接器手册见
[`references/handoff/qcc_and_arkclaw.md`](references/handoff/qcc_and_arkclaw.md)。

### 4.1 可选：企查查二维码登录 Demo

只测试「能不能弹出企查查二维码」时（不带入合同审核）：

```powershell
pip install -r requirements-demo.txt
python demos/qcc_login_demo.py "华为技术有限公司" --login-only --hold-seconds 900
```

demo 会打开本机浏览器，保存登录二维码和查询结果截图到 `output/qcc_login_demo/`，并生成 `qcc_login_demo_latest.html` 本地预览页。

> 注意：早期 `--login-only` 不保持窗口，截图保存后立即退出；当前版本默认保持
> 15 分钟，必要时通过 `--hold-seconds` 显式调整。

## 5. 云端 ArkClaw / 飞书发送

本地包不内置飞书 / 钉钉发送逻辑。正式部署到云端 ArkClaw 时，由 ArkClaw 读取输出产物并调用平台连接器发送即可。建议发送：

- `output/im_review/<timestamp>/合同审核报告_行政版.pdf` —— 行政老师最终阅读对象。
- `output/contract_review.md` 与 `output/合同形式化审核总表.xlsx` —— 备查。
- `output/qcc_login_demo/qcc_result_*.png` —— 企查查查询结果截图。

登录二维码截图默认**不**发送到群里。

## 6. 目录结构

```
contract-review-openclaw-portable/
├── README.md                        # 本文件
├── CHANGELOG.md                     # 版本说明（中文）
├── docs/
│   ├── technical_roadmap.tex        # 技术路线 LaTeX 源
│   └── technical_roadmap.pdf        # 渲染产物
├── skills/
│   ├── contract-formal-review-flow/SKILL.md     # 形式化审核入口 skill
│   └── contract-template-compliance/SKILL.md    # 范式合同对照 skill
├── scripts/
│   ├── contract_loader.py           # docx/pdf/txt 读取（含批注/高亮/表格）
│   ├── contract_extractor.py        # 字段抽取 + template_match 接入
│   ├── contract_rule_checker.py     # YAML 规则引擎
│   ├── contract_report_writer.py    # Markdown / JSON / Excel 输出
│   ├── template_matcher.py          # 形状 + 锚点双门槛范本匹配器
│   └── ...
├── references/
│   ├── rules/horizontal_contract_formal_rules.yaml  # 形式化审核规则
│   ├── schemas/                     # 输出 schema
│   ├── prompts/                     # 老师可复制的提示词
│   ├── templates/中山大学*.docx     # 学校合同范本库
│   └── handoff/qcc_and_arkclaw.md   # QCC / ArkClaw 长篇手册
├── demos/                           # 二维码登录等演示脚本（非默认流程）
├── samples/                         # 测试合同
│   └── sysu/                        # 范式合同对照正反例
├── tests/                           # pytest 测试
├── run_contract_review.py           # 本地命令行入口
└── install_into_openclaw.py         # 安装 / 同步两个 skill 到 ~/.openclaw/skills/
```

## 7. 技术路线 / 架构文档

完整的技术路线（pipeline、skill 拆分原则、范本匹配器双门槛设计、回归验证）见：

- 源文件：[`docs/technical_roadmap.tex`](docs/technical_roadmap.tex)
- 渲染产物：[`docs/technical_roadmap.pdf`](docs/technical_roadmap.pdf)

### 重新渲染

Windows + TeX Live：

```powershell
cd docs
latexmk -xelatex -interaction=nonstopmode technical_roadmap.tex
```

或：

```powershell
xelatex -interaction=nonstopmode docs\technical_roadmap.tex
```

中文字体使用 `xeCJK` + 系统 `Microsoft YaHei` / `SimSun`，Linux 下可改为
`Noto Serif CJK SC` / `Noto Sans CJK SC`。
