# contract-review-openclaw

中山大学横向合同形式化审核本地 OpenClaw 包。

## 安装

1. 解压本包到任意目录。
2. 在 PowerShell 进入解压后的项目根目录。
3. 安装依赖：`pip install -r requirements.txt`
4. 安装 OpenClaw skill：`python install_into_openclaw.py`

安装脚本只安装一个默认 skill：`contract-formal-review-flow`。换目录或换机器后，请重新运行一次安装脚本，因为 skill 内部会写入当前解压目录。

## 给行政老师的用法

老师只需要对 OpenClaw 说：

```text
请帮我审核这个合同，<合同文件完整路径>
```

OpenClaw 默认会先尝试复用本机企查查登录状态；若登录状态不可用，会弹出企查查二维码让老师扫码。企查查核验成功时，会把甲方企业信息带入合同审核；若遇到验证码、访问限制、字段不足或登录失败，会自动退回普通合同审核，并在结果里说明企业核验未完成。

示例：

```text
请帮我审核这个合同，<本项目目录>\samples\华为-中大智算集群可靠性测评技术合作协议-脱敏版.docx
```

OpenClaw 应返回行政老师能直接看的结论、修改事项、补材料事项、企业核验情况、知识产权重点和报告位置。

最终摘要建议采用“简短文字结论 + 表格”的形式。表格应把每个问题和对应合同条款/证据放在同一行，便于行政老师逐项转给项目负责人或合作方修改。

## 本地脚本用法

只做本地审核、不查企查查：

```powershell
python run_contract_review.py "<合同文件完整路径>"
```

使用人工整理的企业核验材料：

```powershell
python run_contract_review.py "<合同文件完整路径>" --company-check "<企业核验文件路径>"
```

`--company-check` 支持 JSON、CSV、XLSX。没有该文件时，甲方工商信息、关联关系、民用非涉密非军工属性会作为人工复核事项留在报告里。

## 企业信息核验

默认提示词会尝试企查查核验甲方企业信息。若企查查登录状态仍有效，会直接查询；若失效，会弹出二维码；若无法形成可用企业核验材料，会退回普通合同审核。

也可以使用人工材料方式：

- 老师提供企查查截图、页面文字或人工核验记录。
- 测试者把材料整理成 `--company-check` 文件。
- 未提供材料时，报告中写明“甲方企业信息未完成外部核验，需补充企查查截图或人工核验记录”。

本包不实现、不支持绕过登录、验证码、付费墙、WAF、反爬策略或访问控制。

如果需要测试“扫码登录企查查后，把甲方企业核验结果带入合同审核”，可以在 OpenClaw dashboard 里说：

```text
请帮我审核这个合同，并通过企查查扫码登录核验甲方企业信息：<合同文件完整路径>
```

OpenClaw 应调用：

```powershell
python demos/qcc_contract_review_demo.py "<合同文件完整路径>" --reuse-profile
```

该流程会先弹出企查查二维码，最多等待 15 分钟让老师扫码。只有检测到扫码登录成功后，才会查询合同里的甲方公司，并生成 `output/qcc_login_demo/company_check_draft_*.json`、`output/qcc_login_demo/qcc_login_demo_latest.html` 预览页，然后用核验文件重新跑合同审核。若超时未登录、遇到验证码、访问限制或字段不足，会退回普通审核，并在结果里说明企业核验未完成。

如果是在受信任的本机上测试，希望减少重复扫码，可以使用浏览器会话复用：

```powershell
python demos/qcc_contract_review_demo.py "<合同文件完整路径>" --reuse-profile
```

第一次仍需扫码；之后同一台机器、同一个项目目录下再次运行时，会先检查 `.browser-profiles/qcc-demo` 中保存的企查查浏览器会话。若会话仍有效，会跳过二维码直接查询；若会话失效，仍会重新弹出二维码。该目录只保存在本机，不会打包进便携 zip。需要清除登录状态时，删除 `.browser-profiles/qcc-demo` 即可。

如果已经有准确的企查查详情页，也可以指定详情页，避免停留在搜索结果页：

```powershell
python demos/qcc_contract_review_demo.py "<合同文件完整路径>" --reuse-profile --company-url "https://www.qcc.com/firm/6b242b475738f45a4dd180564d029aa9.html"
```

## 可选二维码登录 Demo

如果只是测试“能不能弹出企查查二维码”，可以运行独立 demo。这个只生成二维码，不把企业信息带入合同审核。

安装可选依赖：

```powershell
pip install -r requirements-demo.txt
```

运行：

```powershell
python demos/qcc_login_demo.py "华为技术有限公司"
```

只测试二维码截图：

```powershell
python demos/qcc_login_demo.py "华为技术有限公司" --login-only
```

上面这条命令现在也会默认保持窗口 15 分钟。早期版本的 `--login-only` 没有保持窗口，截图保存后会马上退出，这是导致二维码页面很快关闭的原因。

也可以显式指定保持时间：

```powershell
python demos/qcc_login_demo.py "华为技术有限公司" --login-only --hold-seconds 900
```

在 OpenClaw dashboard 里也可以直接说：

```text
请弹出企查查登录二维码，让我扫码测试，只生成二维码，不查询公司。
```

demo 会打开本机浏览器，保存企查查登录二维码截图到 `output/qcc_login_demo/`，并生成 `output/qcc_login_demo/qcc_login_demo_latest.html` 本地预览页。Dashboard 聊天框通常只会显示路径，不会直接嵌入本机 PNG 图片；打开这个 HTML 预览页即可看到二维码截图和后续查询页面截图。

如果继续查询公司，demo 会先等待扫码登录成功；未检测到登录成功时，不会查询公司，也不会生成可用于审核的企业核验材料。

限制：

- 只适合单次、单家公司测试。
- 不保存账号密码。
- 不绕过验证码、登录、WAF、付费墙或访问限制。
- 草稿核验文件必须人工复核后，才能作为 `--company-check` 材料使用。

## 云端 ArkClaw / 飞书发送

本地包不内置飞书、钉钉发送逻辑。正式部署到云端 ArkClaw 时，由 ArkClaw 读取输出产物并调用平台连接器发送消息即可。

企查查流程会稳定产出：

- `output/qcc_login_demo/qcc_login_demo_latest.json`：记录截图路径、预览页路径、企业核验草稿路径和状态。
- `output/qcc_login_demo/qcc_login_demo_latest.html`：本机或云端可查看的截图预览页。
- `output/qcc_login_demo/qcc_result_*.png`：企查查查询结果截图，适合由云端 ArkClaw 上传到飞书。
- `output/contract_review.md` 和 `output/合同形式化审核总表.xlsx`：合同审核报告。

建议云端只发送审核摘要、报告文件和查询结果截图；登录二维码截图默认不发送到群里。

## 目录

- `skills/`：唯一默认 OpenClaw skill。
- `scripts/`：稳定 Python 实现，负责读取文档、抽取字段、规则审核、写报告。
- `demos/`：可选演示脚本，不属于默认审核流程。
- `references/rules/`：审核规则 YAML。
- `references/schemas/`：结构化输出 schema。
- `references/prompts/`：给行政老师复制使用的提示词模板。
- `samples/`：样例文件。
- `tests/`：pytest 测试。
- `run_contract_review.py`：本地命令行入口。
- `install_into_openclaw.py`：安装/同步 OpenClaw skill。

## 输出

- `output/contract_review.md`
- `output/contract_findings_<hash>.json`
- `output/合同形式化审核总表.xlsx`

最终给老师看 Markdown 和 Excel 即可；不要要求老师理解中间 JSON、schema 或规则编号。
