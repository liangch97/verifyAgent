from __future__ import annotations

from pathlib import Path

from scripts.openclaw_global_prompt_config import PLUGIN_ID, update_config


def test_update_config_enables_prompt_plugin(tmp_path: Path) -> None:
    plugin_path = tmp_path / "openclaw-extensions" / PLUGIN_ID
    project_root = tmp_path / "contract-review-openclaw-portable"
    config = {"models": {"providers": {}}}

    updated = update_config(
        config,
        plugin_path=plugin_path,
        project_root=project_root,
        mode="local",
    )

    plugins = updated["plugins"]
    assert plugins["enabled"] is True
    assert str(plugin_path.resolve()) in plugins["load"]["paths"]
    assert plugins["entries"][PLUGIN_ID]["enabled"] is True
    assert plugins["entries"][PLUGIN_ID]["hooks"]["allowPromptInjection"] is True
    assert plugins["entries"][PLUGIN_ID]["config"]["mode"] == "local"
    assert plugins["entries"][PLUGIN_ID]["config"]["contractReviewHome"] == str(project_root.resolve())
    assert plugins["entries"][PLUGIN_ID]["config"]["sampleContractPath"].endswith(".docx")


def test_update_config_preserves_allowlist_and_adds_plugin(tmp_path: Path) -> None:
    plugin_path = tmp_path / "plugin"
    project_root = tmp_path / "project"
    config = {"plugins": {"allow": ["diffs"], "load": {"paths": ["C:/existing"]}}}

    updated = update_config(
        config,
        plugin_path=plugin_path,
        project_root=project_root,
        mode="cloud",
    )

    assert updated["plugins"]["allow"] == ["diffs", PLUGIN_ID]
    assert "C:/existing" in updated["plugins"]["load"]["paths"]
    plugin_config = updated["plugins"]["entries"][PLUGIN_ID]["config"]
    assert plugin_config["mode"] == "cloud"
    assert "sampleContractPath" not in plugin_config
