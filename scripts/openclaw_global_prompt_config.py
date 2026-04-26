from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

PLUGIN_ID = "contract-review-onboarding"


def default_openclaw_config_path() -> Path:
    return Path(os.path.expanduser("~")) / ".openclaw" / "openclaw.json"


def default_plugin_path(project_root: Path) -> Path:
    return project_root / "openclaw-extensions" / PLUGIN_ID


def default_sample_contract_path(project_root: Path) -> Path:
    return (
        project_root
        / "samples"
        / "华为-中大智算集群可靠性测评技术合作协议-脱敏版.docx"
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def update_config(
    config: dict[str, Any],
    *,
    plugin_path: Path,
    project_root: Path,
    mode: str,
) -> dict[str, Any]:
    if mode not in {"local", "cloud"}:
        raise ValueError("mode must be 'local' or 'cloud'")

    next_config = dict(config)
    plugins = _as_dict(next_config.get("plugins")).copy()
    plugins["enabled"] = True

    load = _as_dict(plugins.get("load")).copy()
    paths = [str(item) for item in _as_list(load.get("paths")) if str(item).strip()]
    plugin_path_text = str(plugin_path.resolve())
    if plugin_path_text not in paths:
        paths.append(plugin_path_text)
    load["paths"] = paths
    plugins["load"] = load

    allow = plugins.get("allow")
    if isinstance(allow, list) and allow and PLUGIN_ID not in allow:
        plugins["allow"] = [*allow, PLUGIN_ID]

    entries = _as_dict(plugins.get("entries")).copy()
    entry = _as_dict(entries.get(PLUGIN_ID)).copy()
    entry["enabled"] = True

    hooks = _as_dict(entry.get("hooks")).copy()
    hooks["allowPromptInjection"] = True
    entry["hooks"] = hooks

    plugin_config = _as_dict(entry.get("config")).copy()
    plugin_config["mode"] = mode
    plugin_config["contractReviewHome"] = str(project_root.resolve())
    if mode == "local":
        plugin_config["sampleContractPath"] = str(default_sample_contract_path(project_root).resolve())
    else:
        plugin_config.pop("sampleContractPath", None)
    entry["config"] = plugin_config

    entries[PLUGIN_ID] = entry
    plugins["entries"] = entries
    next_config["plugins"] = plugins
    return next_config


def install_global_prompt(
    *,
    config_path: Path,
    plugin_path: Path,
    project_root: Path,
    mode: str,
    backup: bool = True,
) -> Path | None:
    manifest = plugin_path / "openclaw.plugin.json"
    entry = plugin_path / "index.ts"
    if not manifest.exists() or not entry.exists():
        raise FileNotFoundError(f"OpenClaw plugin files are incomplete: {plugin_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        config = json.load(fh)
    if not isinstance(config, dict):
        raise ValueError(f"OpenClaw config root must be an object: {config_path}")

    backup_path: Path | None = None
    if backup:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = config_path.with_name(f"{config_path.name}.bak.contract-review-{stamp}")
        shutil.copy2(config_path, backup_path)

    next_config = update_config(
        config,
        plugin_path=plugin_path,
        project_root=project_root,
        mode=mode,
    )
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(next_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(config_path)
    return backup_path
