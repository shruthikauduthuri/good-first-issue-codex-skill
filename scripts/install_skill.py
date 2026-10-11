#!/usr/bin/env python3
"""Install the desktop skill without overwriting an existing skill or configuration."""
import argparse
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=Path.home() / ".agents/skills")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / ".agents/skills/good-first-issues"
    destination = args.target.expanduser().resolve() / source.name
    if destination.exists() or destination.is_symlink():
        raise SystemExit(f"Already exists: {destination}. No files were overwritten.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("config.json", "__pycache__", "*.pyc"))
    print(f"Installed: {destination}")
    print("Select Good First Issue Finder in Codex's skill picker. Restart the app if needed.")
    print(f"Configure privately: python3 {destination / 'scripts/configure.py'}")


if __name__ == "__main__":
    main()
