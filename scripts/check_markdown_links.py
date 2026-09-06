#!/usr/bin/env python3
"""Checks every relative markdown link in the repo actually resolves to a real
file. Used by .github/workflows/compose-validate.yml on every PR; also safe to
run by hand (`python3 scripts/check_markdown_links.py`) after moving/renaming
docs.

Deliberately skips http(s)/mailto links (nothing to check locally) and one
known exception: server/scryfall_mcp/ is vendored upstream content (see
CLAUDE.md's Scryfall section) -- its README/attribution files aren't ours to
fix, so a broken link inside them is a pre-existing upstream issue, not a
regression in this repo.
"""

import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", ".venv", "dist", "__pycache__"}
VENDORED_EXCEPTION = os.path.join("server", "scryfall_mcp")

LINK_RE = re.compile(r"\]\(([^)]+)\)")


def find_markdown_files(root: str) -> list[str]:
    md_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if f.endswith(".md"):
                md_files.append(os.path.join(dirpath, f))
    return md_files


def check_links(root: str) -> tuple[int, list[tuple[str, str, str]]]:
    broken: list[tuple[str, str, str]] = []
    checked = 0
    for md in find_markdown_files(root):
        with open(md, encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
        base_dir = os.path.dirname(md)
        for link in LINK_RE.findall(content):
            if link.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path_part = link.split("#", 1)[0]
            if not path_part:
                continue
            resolved = os.path.normpath(os.path.join(base_dir, path_part))
            checked += 1
            if not os.path.exists(resolved):
                if VENDORED_EXCEPTION in os.path.normpath(md):
                    continue
                broken.append((md, link, resolved))
    return checked, broken


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    checked, broken = check_links(root)
    print(f"Checked {checked} relative markdown links.")
    if broken:
        print("BROKEN LINKS:")
        for md, link, resolved in broken:
            print(f"  {md}: '{link}' -> {resolved} (missing)")
        return 1
    print("All relative links resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
