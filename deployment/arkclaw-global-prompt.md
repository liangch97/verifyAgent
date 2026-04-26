# ArkClaw 云端全局提示词部署说明

目标：让 ArkClaw 在默认打招呼或用户询问“怎么用”时，直接告诉行政老师合同审核的简单用法；当用户上传合同或提供文件路径/链接时，直接调用 `contract-formal-review-flow` 完成审核。

## 推荐方式：安装全局提示插件

1. 将本包完整上传到云端 ArkClaw 可访问的固定目录，例如 `/opt/contract-review-openclaw-portable`。
2. 安装合同审核 skill：

```bash
python install_into_openclaw.py
```

3. 安装全局提示插件，并使用云端措辞：

```bash
python install_openclaw_global_prompt.py --mode cloud
```

4. 重启 ArkClaw / OpenClaw gateway，使 `plugins.load.paths` 和 `plugins.entries.contract-review-onboarding` 生效。

插件注入的是稳定 system prompt，不依赖本机 Windows 绝对路径。云端问候会引导老师上传合同或提供文件链接/云端路径。

## 手工方式：复制全局提示词

如果 ArkClaw 平台不允许加载本地插件，就把下面文件中的提示词复制到 ArkClaw 的全局 system prompt / agent prompt 配置里：

```text
references/prompts/openclaw_global_contract_review_prompt.md
```

## 不建议改 dashboard 静态 UI

dashboard 首页的静态占位文字和模型的第一轮回复不是同一个东西。为了可迁移，本包只改模型全局提示词，不直接修改 OpenClaw dashboard 编译产物。这样迁移到云端 ArkClaw 时仍然可复用。
