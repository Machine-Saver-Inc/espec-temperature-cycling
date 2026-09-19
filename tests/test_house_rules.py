"""The rules that used to live only in a checklist.

Every test here replaces something a person had to remember. They are written
against the shape of the code rather than its behaviour, which makes them
unusual - but each one is here because the thing it checks was missed at least
once, and a rule nobody can forget is worth more than a rule written down well.

Where a test fails, its message says what to do, not just what is wrong.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "espec_burnin" / "ui"


def sources(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*.py") if "__pycache__" not in p.parts)


# --- buttons: issue #6 -----------------------------------------------------
#
# Secondary buttons rendered as bare words for weeks. Two things caused it: a
# stylesheet that set some box properties and not others, and buttons built by
# hand in eight different files so no single change could fix them all.


# The one hand-built button: it carries the journal-and-bug mark the README
# tells people to look for, which is not part of the shared icon set.
BUTTON_EXCEPTIONS = {("main_window.py", "Report a problem")}


def test_buttons_are_built_by_the_shared_helper():
    offenders = []
    for path in sources(UI):
        if path.name == "widgets.py":          # where the helper itself lives
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "QPushButton":
                continue
            label = ""
            if node.args and isinstance(node.args[0], ast.Constant):
                label = str(node.args[0].value).strip()
            if (path.name, label) in BUTTON_EXCEPTIONS:
                continue
            offenders.append(f"{path.name}:{node.lineno} QPushButton({label!r})")

    assert not offenders, (
        "these build a button directly instead of using widgets.button(): "
        f"{offenders}. One helper is what keeps every button looking like a "
        "button, and is also where a press gets recorded for the problem report."
    )


def stylesheet_rules(text: str) -> dict[str, str]:
    """Selector -> declarations, for every rule in the stylesheet."""
    without_comments = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return {
        match.group(1).strip().splitlines()[-1].strip(): match.group(2)
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", without_comments)
    }


def test_a_styled_control_is_styled_completely():
    """Issue #6's root cause.

    Setting padding or a corner radius without also setting a border and a
    background makes Qt discard the native appearance of the control, which is
    how buttons came to render as text with nothing to press.
    """
    from espec_burnin.ui.style import build_stylesheet

    for dark in (False, True):
        for selector, body in stylesheet_rules(build_stylesheet(dark)).items():
            if "QPushButton" not in selector:
                continue
            if ":" in selector.split("QPushButton")[-1]:
                continue                        # states inherit the base rule
            # A rule that only nudges padding inherits its box from the base
            # rule. It is establishing a corner radius that makes Qt hand the
            # whole appearance over to the stylesheet.
            if "border-radius" not in body:
                continue
            assert "border:" in body or "border-color" in body, (
                f"{selector} sets a box property but no border. Qt then drops "
                "the native border and the control stops looking clickable."
            )
            assert "background" in body, (
                f"{selector} sets a box property but no background, so Qt drops "
                "the native fill."
            )


@pytest.mark.parametrize("role", ["QPushButton", "QPushButton#Primary"])
def test_every_button_role_describes_its_states(role):
    """A role styled only in its resting state has no pressed or disabled look."""
    from espec_burnin.ui.style import build_stylesheet

    rules = stylesheet_rules(build_stylesheet(False))
    for state in (":hover", ":pressed", ":disabled"):
        assert any(
            selector.startswith(role) and selector.endswith(state)
            for selector in rules
        ), f"{role} has no {state} appearance"


# --- icons: issue #6 -------------------------------------------------------


def test_every_icon_is_legible_at_the_size_it_ships_at():
    """Two glyphs read as an asterisk and a squiggle on the first pass.

    A mark using a small share of its box looks like a speck beside its label,
    which is indistinguishable from a missing icon.
    """
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    from espec_burnin.ui.icons import GLYPHS, SIZE, icon

    QApplication.instance() or QApplication([])
    too_small = []
    for name in GLYPHS:
        image = icon(name, "#000000", SIZE).pixmap(SIZE, SIZE).toImage()
        inked = [
            (x, y)
            for x in range(SIZE)
            for y in range(SIZE)
            if image.pixelColor(x, y).alpha() > 40
        ]
        assert inked, f"the {name!r} icon drew nothing"
        width = max(x for x, _ in inked) - min(x for x, _ in inked) + 1
        height = max(y for _, y in inked) - min(y for _, y in inked) + 1
        if max(width, height) < SIZE * 0.55:
            too_small.append(f"{name} ({width}x{height} of {SIZE}px)")

    assert not too_small, (
        f"these marks are too small to read beside a label: {too_small}. "
        "Redraw them to fill more of the 24-unit grid."
    )


def test_icons_render_in_both_themes():
    """They are tinted from the palette, so a dark machine uses different ink."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    from espec_burnin.ui.icons import GLYPHS, icon

    QApplication.instance() or QApplication([])
    for name in GLYPHS:
        for colour in ("#1a1a1a", "#e6e9ee"):
            assert not icon(name, colour).isNull(), f"{name} is null in {colour}"


# --- the release the checklist used to guard -------------------------------


def changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_this_version_has_a_changelog_entry():
    from espec_burnin import __version__

    assert f"## [{__version__}]" in changelog(), (
        f"CHANGELOG.md has no entry for {__version__}. The release body and the "
        "README are written from it, so a bump without an entry ships a release "
        "page that says nothing."
    )


def test_the_release_notes_carry_a_placeholder_not_a_version():
    """CI substitutes the tag into this file. A number baked in here would ship
    a release page advertising the previous release."""
    notes = (ROOT / "packaging" / "release-notes.md").read_text(encoding="utf-8")
    assert "<version>" in notes
    hard_coded = re.findall(r"\b\d+\.\d+\.\d+\b", notes)
    assert not hard_coded, (
        f"packaging/release-notes.md names versions directly: {hard_coded}. "
        "Use <version> so CI fills it in from the tag."
    )


def test_every_issue_named_in_the_changelog_has_a_test_naming_it():
    """A fix without a named test is rediscovered rather than recognised."""
    issues = set(re.findall(r"issue #(\d+)", changelog()))
    assert issues, "no issues referenced in the changelog - has the format changed?"

    covered = " ".join(
        path.read_text(encoding="utf-8") for path in sources(ROOT / "tests")
    )
    missing = sorted(
        number for number in issues if f"#{number}" not in covered
    )
    assert not missing, (
        f"no test mentions issue(s) {missing}. Name the issue in the test that "
        "pins its fix, so a regression is recognised as one."
    )


def test_the_version_can_be_read_from_the_command_line():
    """Somebody on the phone to a chamber PC with no internet needs this."""
    from espec_burnin import __version__

    result = subprocess.run(
        [sys.executable, "-m", "espec_burnin.ui.app", "--version"],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout


def release_workflow() -> str:
    return (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def test_the_release_workflow_checks_what_it_published():
    """Downloading the published asset and verifying it used to be a step a
    person remembered, and forgot at least once."""
    workflow = release_workflow()
    assert "SHA256SUMS" in workflow
    assert "sha256sum -c" in workflow, (
        "the release workflow publishes checksums but never verifies the "
        "published files against them"
    )


def test_the_release_workflow_refuses_a_tag_that_is_not_on_main():
    """A push that times out can leave a tag pointing at a commit on no
    branch. That happened once and was caught by hand."""
    assert "merge-base --is-ancestor" in release_workflow(), (
        "nothing stops a release being cut from a commit that is not on main"
    )
