#!/usr/bin/env bash
# install.sh — link this repo's scripts into OpenClaw and the contract-review portable package.
# Idempotent: re-running is safe.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}/contract-review-feishu-bot/config.json"

if [ ! -f "$CFG" ]; then
    echo "[install] missing config: $CFG"
    echo "[install] please follow DEPLOYMENT.md step 6 first."
    exit 1
fi

PORTABLE_DIR="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("OPENCLAW_PORTABLE_DIR","/root/contract-review-openclaw-portable"))' "$CFG")"
SKILLS_DIR="${HOME}/.openclaw/skills/contract-formal-review-flow"
TARGET_BIN_DIR="${HOME}"

echo "[install] portable dir : $PORTABLE_DIR"
echo "[install] skills dir   : $SKILLS_DIR"
echo "[install] script target: $TARGET_BIN_DIR"

# 1. SKILL.md
mkdir -p "$SKILLS_DIR"
cp -v "$REPO_DIR/skills/contract-formal-review-flow/SKILL.md" "$SKILLS_DIR/SKILL.md"

# 2. main scripts → /root/ (or $HOME)
cp -v "$REPO_DIR/full_qcc_review.py"   "$TARGET_BIN_DIR/full_qcc_review.py"
cp -v "$REPO_DIR/admin_report.py"      "$TARGET_BIN_DIR/admin_report.py"
cp -v "$REPO_DIR/llm_field_extract.py" "$TARGET_BIN_DIR/llm_field_extract.py"
chmod +x "$TARGET_BIN_DIR/full_qcc_review.py"

# 3. v2 QCC scraper → portable demos
if [ -d "$PORTABLE_DIR/demos" ]; then
    if [ -f "$PORTABLE_DIR/demos/qcc_login_demo.py" ] && [ ! -f "$PORTABLE_DIR/demos/qcc_login_demo.py.orig" ]; then
        cp -v "$PORTABLE_DIR/demos/qcc_login_demo.py" "$PORTABLE_DIR/demos/qcc_login_demo.py.orig"
    fi
    cp -v "$REPO_DIR/scripts/qcc_login_demo.py" "$PORTABLE_DIR/demos/qcc_login_demo.py"
else
    echo "[install] WARNING: $PORTABLE_DIR/demos not found; skipping qcc_login_demo.py"
fi

# 4. openclaw workspace bootstrap (IDENTITY/USER/SOUL + delete BOOTSTRAP.md)
WS_DIR="${HOME}/.openclaw/workspace"
if [ -d "$WS_DIR" ]; then
    for f in IDENTITY.md USER.md SOUL.md; do
        if [ -f "$REPO_DIR/openclaw-workspace/$f" ]; then
            cp -v "$REPO_DIR/openclaw-workspace/$f" "$WS_DIR/$f"
        fi
    done
    if [ -f "$WS_DIR/BOOTSTRAP.md" ]; then
        rm -v "$WS_DIR/BOOTSTRAP.md"
    fi
else
    echo "[install] WARNING: $WS_DIR not found; skipping workspace bootstrap"
fi

echo "[install] done."
echo "[install] now run: openclaw gateway"
