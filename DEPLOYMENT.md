# 部署指南：Linux/WSL + 飞书机器人

> 目标环境：Windows 11 + WSL2 (Ubuntu 22.04)，或裸 Linux。本文以 WSL2 为基线。

## 1. 系统依赖

```bash
# 在 WSL Ubuntu 内执行
sudo apt update
sudo apt install -y python3 python3-pip python3-venv chromium-browser fonts-noto-cjk poppler-utils
```

> `chromium-browser`：QCC 扫码登录所需可见浏览器
> `fonts-noto-cjk`：reportlab 生成 PDF 需要的中文字体（如已装系统中文字体可省略）
> `poppler-utils`：用于 `pdftotext` 抽查渲染结果

## 2. 安装 Node.js 22 + OpenClaw

OpenClaw 是飞书 ↔ Agent ↔ LLM 的网关，本仓库依赖它把消息分发给本地脚本。

```bash
# 使用 NodeSource 源安装 Node 22
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

# 全局安装 openclaw
mkdir -p ~/.npm-global
npm config set prefix '~/.npm-global'
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc
source ~/.bashrc

npm install -g openclaw@2026.4.26   # 锁定经过验证的版本
```

验证：

```bash
openclaw --version    # → 2026.4.26
which openclaw        # → /root/.npm-global/bin/openclaw
```

## 3. 安装合同审核基础包

本仓库依赖 OpenClaw portable 合同审核包（提供规则引擎和加载器）。

```bash
# 把 contract-review-openclaw-portable 解压到 /root/
unzip contract-review-openclaw-portable.zip -d /root/
cd /root/contract-review-openclaw-portable
pip install -r requirements.txt
python install_into_openclaw.py     # 写入 OpenClaw 技能目录
```

## 4. 克隆本仓库

```bash
cd ~
git clone https://github.com/liangch97/contract-review-feishu-bot.git
cd contract-review-feishu-bot
pip install -r requirements.txt
```

## 5. 创建飞书企业自建应用

1. 登录 [飞书开放平台](https://open.feishu.cn/app)，创建「企业自建应用」
2. 「凭证与基础信息」记下 **App ID** 和 **App Secret**
3. 「权限管理」开启：
   - `im:message`（接收和发送消息）
   - `im:message.group_at_msg`（接收群中 @ 机器人消息）
   - `im:resource`（下载用户上传的文件）
4. 「事件与回调」：
   - 订阅方式选 **使用长连接接收事件**
   - 事件订阅：勾选 `接收消息 v2.0` (`im.message.receive_v1`)
5. 「版本管理与发布」→ 创建版本 → 发布
6. 「机器人」→ 启用机器人功能，从飞书 App 通讯录中和机器人开始私聊
7. 给机器人发一条消息，在 Bot 后台「事件与回调 → 调试」可看到 `sender.sender_id.open_id` 即为 `USER_OPEN_ID`，记下来

## 6. 写入本机配置

```bash
mkdir -p ~/.config/contract-review-feishu-bot
cat > ~/.config/contract-review-feishu-bot/config.json << 'EOF'
{
  "APP_ID": "cli_xxxxxxxxxxxx",
  "APP_SECRET": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "USER_OPEN_ID": "ou_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "OPENCLAW_PORTABLE_DIR": "/root/contract-review-openclaw-portable"
}
EOF
chmod 600 ~/.config/contract-review-feishu-bot/config.json
```

## 7. 配置 OpenClaw

### 7.1 添加飞书 channel

```bash
mkdir -p ~/.openclaw
cat > ~/.openclaw/openclaw.json << 'EOF'
{
  "version": 1,
  "agents": {
    "main": {
      "model": "minimax/MiniMax-M2.7-highspeed",
      "providers": {
        "minimax": { "apiKey": "<YOUR_MINIMAX_API_KEY>" }
      }
    }
  },
  "channels": {
    "feishu": {
      "default": {
        "mode": "websocket",
        "appId": "cli_xxxxxxxxxxxx",
        "appSecret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "agentId": "main",
        "allowFrom": ["ou_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"]
      }
    }
  }
}
EOF
chmod 600 ~/.openclaw/openclaw.json
```

> 模型 provider 可换成任意 OpenClaw 支持的：MiniMax / Anthropic / OpenAI / SiliconFlow / 火山方舟 等。

### 7.2 安装本仓库的技能与脚本

仓库根目录运行：

```bash
bash install.sh
```

`install.sh` 会：
- 把 `skills/contract-formal-review-flow/SKILL.md` 拷到 `~/.openclaw/skills/contract-formal-review-flow/`
- 把 `full_qcc_review.py` 和 `admin_report.py` 链接到 `/root/`（脚本会被 SKILL.md 调用）
- 把 v2 版 `scripts/qcc_login_demo.py` 替换到 `${OPENCLAW_PORTABLE_DIR}/demos/`（启用 15 字段抓取）

## 8. 启动 gateway

```bash
openclaw gateway
```

预期日志（前 30s）：

```
[gateway] http server listening
[feishu] feishu[default]: bot open_id resolved: ou_...
[feishu] feishu[default]: WebSocket client started
[gateway] ready
```

## 9. 端到端测试

在飞书机器人私聊里：

**情景 A：文字路径触发**
```
请帮我审核这个合同：/root/contract-review-openclaw-portable/samples/华为-中大智算集群可靠性测评技术合作协议-脱敏版.docx
```

**情景 B：文件上传触发（推荐）**
1. 拖一份合同 docx 到聊天框
2. 附一句「审核这个」（或不发文字也可）
3. 发送

无论 A/B，预期机器人行为：
1. 先推送企查查 QR 二维码图片
2. 你扫码登录企查查
3. 推送「企业核查完成 → 开始合同审核」状态
4. 推送 `合同审核报告_行政版.pdf`
5. 仅回一句「审核完成，行政版PDF已推送。」（不输出任何文字摘要）

## 10. 常见问题

### 10.1 `messages must not be empty (2013)` 错误

**症状**：发送 `/new` 清空对话后，下一条消息 agent 报错。

**根因**：OpenClaw 2026.4.26 + MiniMax provider 不兼容；`/new` 重置后产生空 user prompt 被模型拒绝。

**解决**：
- 不用 `/new`，直接发新指令即可（每个合同审核都是独立的脚本调用，不依赖会话状态）
- 如需彻底清空：
  ```bash
  cd ~/.openclaw/agents/main/sessions
  ls *.jsonl 2>/dev/null | grep -v reset | xargs -I {} mv {} {}.archived.$(date +%s)
  pkill -f "openclaw gateway"
  openclaw gateway &
  ```

### 10.2 飞书收不到 PDF

检查日志 `/tmp/openclaw/openclaw-2026-MM-DD.log` 中是否有 `replies=N`，N 应 ≥ 2。

如果脚本日志显示 `[fs_file] OK` 但飞书没收到，确认：
- 飞书应用「权限管理」开启了 `im:message`
- App ID / Secret / User Open ID 与配置文件完全一致

### 10.3 企查查抓不到字段

打开 `${OPENCLAW_PORTABLE_DIR}/output/qcc_login_demo/qcc_text_<company>_<timestamp>.txt` 查看原始文本。如布局更新，更新 `scripts/qcc_login_demo.py` 中的 `extract_qcc_card_fields_v2` 标签列表。

### 10.4 Chromium 启动失败

WSL2 默认无 X server，可启用 WSLg（Win11 自带）或装 VcXsrv；也可改用 headless：编辑 `qcc_login_demo.py` 把 `--headless=false` 切到 `--headless=new`，但企查查 headless 容易触发风控。

## 11. 安全注意

- `config.json` 含敏感信息，权限设为 600，不要进 git
- App Secret 泄漏会导致他人冒用机器人，发现后立即在飞书后台旋转
- QCC 浏览器配置目录 `${OPENCLAW_PORTABLE_DIR}/.browser-profiles/qcc-demo` 含登录 cookie，禁止打包发布

## 12. 升级与回滚

升级 OpenClaw 版本前，备份：

```bash
cp -r ~/.openclaw ~/.openclaw.bak.$(date +%Y%m%d)
```

回滚：

```bash
npm install -g openclaw@2026.4.26   # 已知良好版本
```
