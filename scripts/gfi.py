#!/usr/bin/env python3
"""Terminal entry point for the same verified finder used by the Codex skill."""
import os
from pathlib import Path
import runpy


def main():
    root = Path(__file__).resolve().parents[1]
    # Reuse the GUI's private configuration when no explicit override is supplied.
    installed = Path.home() / ".agents/skills/good-first-issues/scripts/config.json"
    project = root / ".agents/skills/good-first-issues/scripts/config.json"
    if not os.getenv("GFI_CONFIG") and not os.getenv("GFI_ENDPOINT"):
        if project.is_file():
            os.environ["GFI_CONFIG"] = str(project)
        elif installed.is_file():
            os.environ["GFI_CONFIG"] = str(installed)
    runpy.run_path(str(root / ".agents/skills/good-first-issues/scripts/find_issues.py"), run_name="__main__")


if __name__ == "__main__":
    main()
