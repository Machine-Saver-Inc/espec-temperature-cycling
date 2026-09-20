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
sys.path.insert(0, str(ROOT))          # tools/ is not an installed package


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

    from espec_burnin.ui.icons import SIZE, icon, names

    QApplication.instance() or QApplication([])
    assert names(), "the icon set is empty"
    too_small = []
    for name in names():
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

    from espec_burnin.ui.icons import icon, names

    QApplication.instance() or QApplication([])
    for name in names():
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


# --- what a release page says: issue #8 ------------------------------------
#
# The release body was the install instructions, and the program's What's new
# button shows the release body. Someone already running the program pressed it
# and was told how to download the program.


def versions_in_changelog() -> list[str]:
    return re.findall(r"^## \[([^\]]+)\]", changelog(), re.M)


def test_every_release_says_what_changed_in_plain_words():
    from tools.release_notes import summary

    missing = [v for v in versions_in_changelog() if not summary(v, changelog())]
    assert not missing, (
        f"these versions have no plain-language summary: {missing}. Write a "
        "sentence or two before the first ### section, for somebody standing "
        "at a chamber rather than for the repository."
    )


# The tells of a summary written for the repo rather than for the person using
# the program. Not a style opinion: these appeared in a release page a user
# read and called nonsense.
JARGON = (
    ".py", "tests/", "pytest", "ruff", " CI ", "workflow", "commit",
    "stylesheet", "urlopen", "refactor", "regression test",
)


def test_the_summaries_avoid_developer_jargon():
    from tools.release_notes import summary

    offenders = []
    for version in versions_in_changelog():
        # Matched with their spaces intact: stripping " CI " to "ci" finds it
        # inside "recipe", which is how this test first failed on its own
        # perfectly readable prose.
        text = " " + summary(version, changelog()).lower() + " "
        for tell in JARGON:
            if tell.lower() in text:
                offenders.append(f"{version}: {tell.strip()!r}")
    assert not offenders, (
        f"these summaries read like repository notes: {offenders}. The release "
        "page is what a technician sees when they press What's new."
    )


def test_the_release_body_leads_with_the_changes():
    from espec_burnin import __version__
    from tools.release_notes import compose

    body = compose(__version__)
    assert body.startswith(f"## What's new in {__version__}")
    assert body.index("What's new") < body.index("## Download"), (
        "the download section comes first, which is what issue #8 was about"
    )
    assert "<version>" not in body, "a placeholder survived into the release body"
    assert __version__ in body


def test_the_workflow_builds_the_body_with_the_composer():
    assert "tools/release_notes.py" in release_workflow(), (
        "the release workflow still pastes the install template as the body"
    )


# --- the shell: what every Machine Saver program has in common -------------


def test_the_icons_come_from_the_named_library():
    """One maintained set, not hand-drawn glyphs. Two of those shipped
    illegible before this was a rule."""
    from espec_burnin.ui.icons import ICON_DIR, LIBRARY

    assert LIBRARY == "Lucide"
    source = (ICON_DIR / "SOURCE.md").read_text(encoding="utf-8")
    assert "lucide.dev" in source
    assert (ICON_DIR / "LICENSE").is_file(), "the library's licence must ship with it"
    sample = (ICON_DIR / "back.svg").read_text(encoding="utf-8")
    assert "lucide-static" in sample, "icons must be the upstream files, not redrawn"
    assert "currentColor" in sample, "an icon that cannot be tinted is invisible in dark"


def test_back_is_on_the_left_and_the_forward_action_on_the_right():
    """It was the other way round, which is not what any other application
    does. Enforced on the helper, because that is the only place it is decided."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    from espec_burnin.ui.widgets import action_bar, button

    QApplication.instance() or QApplication([])
    back = button("Back", "back")
    forward = button("Continue", "forward")
    extra = button("Something else", "edit")
    row = action_bar(back=back, forward=forward, extras=[extra])

    order = [row.itemAt(i).widget() for i in range(row.count())]
    order = [w for w in order if w is not None]
    assert order[0] is back, "Back belongs on the left"
    assert order[-1] is forward, "the action that moves forward belongs on the right"
    assert order.index(extra) < order.index(forward)


@pytest.fixture(scope="module")
def app():
    """A Qt application, for the tests below that build real widgets."""
    pytest.importorskip("PySide6.QtWidgets")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from espec_burnin.ui.style import STYLESHEET

    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(STYLESHEET)
    return application


def test_the_footer_carries_the_version_the_maker_and_the_report_button(app):
    """The three things every Machine Saver program shows on every screen."""
    from PySide6.QtWidgets import QLabel

    from espec_burnin import __version__
    from espec_burnin.ui.main_window import MainWindow

    window = MainWindow()
    assert window.report_button.text() == "Report a problem"
    assert not window.report_button.icon().isNull()
    assert __version__ in window.version_label.text()
    assert window.check_now.text() == "Check for updates"

    labels = [w.text() for w in window.findChildren(QLabel) if w.text()]
    assert any("Created by Machine Saver Inc" == t for t in labels), (
        "the footer must say who made it"
    )
    window.close()


def test_the_maker_mark_shows_the_logo(app):
    from PySide6.QtWidgets import QLabel

    from espec_burnin.ui.widgets import maker_mark

    mark = maker_mark()
    pixmaps = [w for w in mark.findChildren(QLabel) if not w.pixmap().isNull()]
    assert pixmaps, "the Machine Saver mark is missing from the footer"


def buttons_declared_in_source() -> list[tuple[str, str, str]]:
    """Every button the interface builds, as (file, label, icon name)."""
    found = []
    for path in sources(UI):
        if path.name == "widgets.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in ("button", "primary"):
                continue
            args = [a.value if isinstance(a, ast.Constant) else None for a in node.args]
            label = args[0] if args else None
            glyph = args[1] if len(args) > 1 else None
            if label is None:
                continue
            found.append((path.name, str(label), str(glyph) if glyph else ""))
    return found


def test_every_button_asks_for_a_mark_the_library_has():
    """A name the set does not hold renders nothing and only logs. One shipped
    that way - `speed` for an icon vendored as `gauge`."""
    pytest.importorskip("PySide6.QtWidgets")
    from espec_burnin.ui.icons import names

    available = set(names())
    assert available, "no icons vendored"

    missing = [
        f"{where}: {label!r} asks for {glyph!r}"
        for where, label, glyph in buttons_declared_in_source()
        if not glyph or glyph not in available
    ]
    assert not missing, (
        f"{missing}\nEvery button carries a mark from the library. Pick an "
        f"existing name, or vendor a new one and record it in "
        f"resources/icons/SOURCE.md and in the skill's button register."
    )


def test_no_two_buttons_say_the_same_thing_with_different_marks():
    """The same words must mean the same mark, or the vocabulary stops being
    a vocabulary."""
    seen: dict[str, set[str]] = {}
    for _, label, glyph in buttons_declared_in_source():
        seen.setdefault(label, set()).add(glyph)
    inconsistent = {label: marks for label, marks in seen.items() if len(marks) > 1}
    assert not inconsistent, f"same label, different marks: {inconsistent}"
