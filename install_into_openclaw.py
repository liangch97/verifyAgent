from __future__ import annotations

import os
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "skills"
DST = Path(os.path.expanduser("~")) / ".openclaw" / "skills"
OPENCLAW_NPM_SKILLS = Path(os.path.expanduser("~")) / "AppData" / "Roaming" / "npm" / "node_modules" / "openclaw" / "skills"

MAIN_SKILL = "contract-formal-review-flow"
LEGACY_SKILLS = [
    "contract-doc-extractor",
    "contract-rule-checker",
    "contract-report-writer",
    "company-registry-browser-check",
]
PLACEHOLDERS = {"{{CONTRACT_REVIEW_HOME}}": str(HERE)}


def _targets() -> list[Path]:
    targets = [DST]
    if OPENCLAW_NPM_SKILLS.exists():
        targets.append(OPENCLAW_NPM_SKILLS)
    return targets


def _render_placeholders(skill_dir: Path) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return
    text = skill_md.read_text(encoding="utf-8")
    for key, value in PLACEHOLDERS.items():
        text = text.replace(key, value)
    skill_md.write_text(text, encoding="utf-8")


def sync() -> None:
    targets = _targets()
    source_skill = SRC / MAIN_SKILL
    if not source_skill.is_dir():
        raise FileNotFoundError(f"main skill not found: {source_skill}")

    for target_root in targets:
        target_root.mkdir(parents=True, exist_ok=True)

        target = target_root / MAIN_SKILL
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source_skill, target)
        _render_placeholders(target)
        print(f"[sync] {MAIN_SKILL:32s} -> {target}")

        for legacy_name in LEGACY_SKILLS:
            legacy_target = target_root / legacy_name
            if legacy_target.exists():
                shutil.rmtree(legacy_target)
                print(f"[cleanup] removed legacy skill -> {legacy_target}")

    print(f"[done] synced 1 skill to {len(targets)} location(s).")


if __name__ == "__main__":
    sync()
