#!/usr/bin/env python3
"""Fail if an internal network address is committed.

CGNAT (100.64/10, which is what a tailnet hands out), RFC1918 ranges and internal
hostnames describe the network to anyone who reads a public repository. Configuration
belongs in an environment variable or a JSON file the operator supplies.
"""
from __future__ import annotations

import pathlib
import re
import sys

PATTERNS = [
    re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
]
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
SKIP_EXT = {".png", ".jpg", ".gif", ".pdf", ".zip", ".gz", ".ico", ".woff", ".woff2"}


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent
    findings = 0
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_EXT or path.stat().st_size > 1_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for pattern in PATTERNS:
                match = pattern.search(line)
                if match:
                    print(f"{path.relative_to(root)}:{number}: {match.group(0)}")
                    findings += 1
    print(f"{findings} internal address(es) in tracked files")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
