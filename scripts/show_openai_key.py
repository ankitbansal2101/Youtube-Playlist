#!/usr/bin/env python3
"""
Print which OPENAI_API_KEY the app will use (masked). Run from project root:

  python scripts/show_openai_key.py

Uses ``get_openai_api_key()`` like the app (reloads ``.env`` each time).
"""
from __future__ import annotations

import sys

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import config  # noqa: E402, F401

from config import get_openai_api_key  # noqa: E402


def main() -> None:
    key = get_openai_api_key()
    if not key:
        print("OPENAI_API_KEY: (not set after loading .env)")
        print(f"  Looked for: {config.PROJECT_ROOT / '.env'}")
        return
    # Fingerprint only — never print full secret
    tail = key[-4:] if len(key) >= 4 else "****"
    prefix = key[:12] if len(key) >= 12 else key[: len(key) // 2] + "…"
    print("OPENAI_API_KEY in use (masked):")
    print(f"  prefix: {prefix}…")
    print(f"  last 4: …{tail}")
    print(f"  length: {len(key)} chars")
    # Heuristic: user pasted key with accidental quotes/newline
    if key[0] in "'\"" or key[-1] in "'\"":
        print("  WARNING: key may include extra quote characters — remove quotes in .env")
    if "\n" in key or "\r" in key:
        print("  WARNING: key contains newline — use a single line in .env")


if __name__ == "__main__":
    main()
