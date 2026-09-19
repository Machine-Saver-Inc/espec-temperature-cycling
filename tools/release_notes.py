#!/usr/bin/env python3
"""Compose a release body: what changed first, then how to install it.

    python tools/release_notes.py 0.15.0 > NOTES.md

The release page serves two people who want opposite things. Someone arriving
for the first time needs the download and the install steps. Someone already
running the program - who pressed **What's new** inside it - needs to know what
changed, and was instead handed a page of instructions for software they had
already installed. That was issue #8.

So the body leads with the plain-language summary from the top of this
version's CHANGELOG entry, and the download section follows it. The detailed
bullets stay in the repository, linked.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
TEMPLATE = ROOT / "packaging" / "release-notes.md"
REPO = "Machine-Saver-Inc/espec-temperature-cycling"


def entry(version: str, text: str | None = None) -> str:
    """Everything under this version's heading, up to the next version."""
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\]\s*$(.*?)(?=^## \[|\Z)", re.M | re.S
    )
    found = pattern.search(text)
    return found.group(1).strip() if found else ""


def summary(version: str, text: str | None = None) -> str:
    """The plain-language lead: the prose before the first ### section.

    Written for somebody standing at a chamber, not for the repository.
    """
    body = entry(version, text)
    if not body:
        return ""
    # Split on the first ### heading wherever it is, including at the very
    # start. Partitioning on "\n### " missed an entry whose first line was
    # already a heading, and called the bullets underneath it a summary.
    lead = re.split(r"^### ", body, maxsplit=1, flags=re.M)[0]
    return lead.strip()


def compose(version: str) -> str:
    lead = summary(version)
    if not lead:
        raise SystemExit(
            f"CHANGELOG.md has no plain-language summary under ## [{version}]. "
            "Write a sentence or two, before the first ### section, saying what "
            "changed for somebody using the program."
        )

    template = TEMPLATE.read_text(encoding="utf-8").replace("<version>", version)
    return "\n".join([
        f"## What's new in {version}",
        "",
        lead,
        "",
        f"The full list of changes is in "
        f"[CHANGELOG.md](https://github.com/{REPO}/blob/v{version}/CHANGELOG.md).",
        "",
        "---",
        "",
        template.strip(),
        "",
    ])


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    print(compose(argv[1].lstrip("v")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
