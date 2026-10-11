#!/usr/bin/env python3
"""Write desktop configuration without displaying the shared key."""
import getpass
import json
import os
from pathlib import Path
from find_issues import validate_endpoint


def main():
    path = Path(__file__).with_name("config.json")
    endpoint = validate_endpoint(input("Finder service URL (ending in /find): ").strip())
    key = getpass.getpass("Shared finder API key (hidden): ").strip()
    if not key:
        raise SystemExit("A shared key is required.")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"endpoint": endpoint, "api_key": key, "timeout": 90}, f, indent=2)
        f.write("\n")
    print(f"Configuration saved to {path}")


if __name__ == "__main__":
    main()
