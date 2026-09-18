"""The README has to match the release it ships with.

A public repo whose README shows screens that no longer exist, or links images
that were never committed, is worse than one with no screenshots at all.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def referenced_images() -> list[str]:
    return IMAGE_PATTERN.findall(README.read_text(encoding="utf-8"))


def tracked_files() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return set(out.stdout.split())


def test_the_readme_shows_the_program():
    """Screenshots are required, not optional."""
    images = referenced_images()
    assert len(images) >= 4, "the README must show the real screens"


@pytest.mark.parametrize("relative", referenced_images())
def test_every_readme_image_exists(relative):
    assert (ROOT / relative).is_file(), f"{relative} is referenced but missing"


@pytest.mark.parametrize("relative", referenced_images())
def test_every_readme_image_is_committed(relative):
    """A screenshot that exists only locally renders as a broken image online."""
    tracked = tracked_files()
    if not tracked:
        pytest.skip("not a git checkout")
    assert relative in tracked, f"{relative} is not tracked by git"


def test_the_readme_leads_with_the_download():
    text = README.read_text(encoding="utf-8")
    assert "releases/latest" in text, "the README must link the latest release"
    download = text.index("## Download")
    assert download < text.index("## How to use it")


def test_the_screenshot_tool_is_committed():
    """The images have to be reproducible, not hand-taken."""
    tracked = tracked_files()
    if not tracked:
        pytest.skip("not a git checkout")
    assert "tools/screenshots.py" in tracked
