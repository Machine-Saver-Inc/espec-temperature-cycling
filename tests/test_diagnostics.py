"""The report-a-problem button.

The report goes to a public repository and is filled in for the user, so it has
to carry what shortens a diagnosis, leave out what identifies the machine, and
survive being too long for an address bar.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

from espec_burnin import __version__
from espec_burnin.core.diagnostics import (
    MAX_URL_CHARS,
    Report,
    environment,
    issue_url,
    read_log_tail,
    redact,
)

CONTEXT = {
    "Screen open": "Running a burn-in",
    "Chamber": "Espec BTZ-133 — Serial 0612223",
    "Port": "COM3",
    "Run in progress": "yes",
}


def a_report(**kwargs) -> Report:
    base = dict(kind="bug", summary="Chamber stalls", description="It stops at -18.",
                context=CONTEXT)
    base.update(kwargs)
    return Report(**base)


# --- what goes in -----------------------------------------------------------

def test_the_version_is_always_reported():
    """Without it, no report can be placed against a release."""
    assert environment()["Program version"] == __version__
    assert "Program version" in a_report().body()


def test_the_screen_and_the_chamber_are_carried():
    body = a_report().body()
    assert "Running a burn-in" in body
    assert "Espec BTZ-133" in body
    assert "COM3" in body


def test_a_bug_asks_for_what_a_bug_needs():
    body = a_report(kind="bug").body()
    assert "What happened" in body
    assert "Steps to reproduce" in body


def test_an_improvement_does_not_ask_for_steps_to_reproduce():
    body = a_report(kind="improvement").body()
    assert "What would be better" in body
    assert "Steps to reproduce" not in body


def test_the_two_kinds_are_titled_and_labelled_differently():
    bug = a_report(kind="bug")
    improvement = a_report(kind="improvement")
    assert bug.title.startswith("[Bug]")
    assert improvement.title.startswith("[Improvement]")
    assert bug.label == "bug"
    assert improvement.label == "enhancement"


def test_an_empty_summary_still_produces_a_usable_title():
    assert a_report(summary="").title == "[Bug] Unexpected behaviour"
    assert a_report(kind="improvement", summary="").title == \
        "[Improvement] Suggested improvement"


def test_the_state_table_renders_as_a_table():
    """A blank line between the header and the rows stops GitHub drawing it."""
    body = a_report().body(include_log=False)
    block = body[body.index("| | |"):].split("\n\n")[0].splitlines()
    assert len(block) > 3
    assert all(line.startswith("|") for line in block)


# --- what stays out ---------------------------------------------------------

def test_the_home_directory_is_never_posted():
    """Reports go to a public repo, and a Windows home path names the account."""
    home = str(Path.home())
    assert home not in redact(f"{home}/.espec-burn-in/log")
    assert redact(f"{home}/x").startswith("~")


def test_context_values_are_redacted_too():
    home = str(Path.home())
    body = Report(context={"Results folder": f"{home}/Documents/results"}).body()
    assert home not in body
    assert "~" in body


def test_a_missing_log_is_not_an_error(tmp_path):
    assert read_log_tail(path=tmp_path / "nothing.log") == []


def test_the_log_tail_is_redacted(tmp_path):
    home = str(Path.home())
    log = tmp_path / "app.log"
    log.write_text(f"opened {home}/.espec-burn-in/settings.json\n", encoding="utf-8")
    assert home not in "\n".join(read_log_tail(path=log))


def test_only_the_tail_of_the_log_is_taken(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(f"line {i}" for i in range(500)), encoding="utf-8")
    tail = read_log_tail(lines=25, path=log)
    assert len(tail) == 25
    assert tail[-1] == "line 499"


# --- getting it to GitHub ---------------------------------------------------

def test_the_url_carries_the_title_label_and_body():
    url, trimmed = issue_url(a_report())
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["title"][0].startswith("[Bug]")
    assert query["labels"][0] == "bug"
    assert "Chamber stalls" in query["title"][0] or "It stops at -18." in query["body"][0]
    assert not trimmed


def test_the_label_matches_one_that_exists_on_the_repository():
    """github ignores nothing here - an unknown label is a broken prefill."""
    assert a_report(kind="bug").label in {"bug", "enhancement"}
    assert a_report(kind="improvement").label in {"bug", "enhancement"}


def test_a_long_log_is_dropped_rather_than_producing_a_broken_url():
    noisy = a_report(log_tail=[f"2026-09-18 17:0{i % 10} WARNING something" * 8
                               for i in range(200)])
    url, trimmed = issue_url(noisy)
    assert len(url) <= MAX_URL_CHARS
    assert trimmed, "the log should have been dropped to fit"
    # ...but the report itself still holds everything, for the clipboard.
    assert len(noisy.body()) > len(urllib.parse.urlparse(url).query)


def test_an_enormous_description_still_yields_a_valid_url():
    huge = a_report(description="x" * 40000)
    url, trimmed = issue_url(huge)
    assert len(url) <= MAX_URL_CHARS
    assert trimmed
    assert url.startswith("https://github.com/")


def test_special_characters_survive_the_url():
    report = a_report(summary="Fails at −20 °C & stalls", description="a=b&c=d #1")
    url, _ = issue_url(report)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert "−20 °C & stalls" in query["title"][0]
    assert "a=b&c=d #1" in query["body"][0]


def test_the_report_never_raises_on_odd_context():
    Report(context={"weird": None, "blank": "", "number": 42}).body()
