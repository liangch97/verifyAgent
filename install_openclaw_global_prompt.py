from __future__ import annotations

import argparse
from pathlib import Path

from scripts.openclaw_global_prompt_config import (
    PLUGIN_ID,
    default_openclaw_config_path,
    default_plugin_path,
    install_global_prompt,
)

HERE = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the contract-review global prompt plugin into OpenClaw."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_openclaw_config_path(),
        help="Path to openclaw.json. Defaults to ~/.openclaw/openclaw.json.",
    )
    parser.add_argument(
        "--plugin-path",
        type=Path,
        default=default_plugin_path(HERE),
        help="Path to the contract-review-onboarding OpenClaw plugin directory.",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "cloud"],
        default="local",
        help="Use local Windows-path wording or cloud ArkClaw upload/link wording.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a timestamped backup of openclaw.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    backup_path = install_global_prompt(
        config_path=args.config,
        plugin_path=args.plugin_path,
        project_root=HERE,
        mode=args.mode,
        backup=not args.no_backup,
    )
    print(f"[done] enabled OpenClaw plugin: {PLUGIN_ID}")
    print("[note] restart the OpenClaw gateway/dashboard for config changes to load.")
    if backup_path:
        print(f"[backup] {backup_path}")


if __name__ == "__main__":
    main()
