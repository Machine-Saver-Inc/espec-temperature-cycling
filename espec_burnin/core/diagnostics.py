"""What to tell us when something goes wrong.

Gathers the facts that actually shorten a diagnosis -- version, platform, which
screen was open, how the chamber is connected, what the run was doing -- and
turns them into a filled-in issue.

Deliberately free of Qt so the report can be built and tested without a window,
and so what gets posted is inspectable rather than assembled inside a dialog.

The repository is public, so paths under the user's home directory are reduced
to ``~`` before anything is shown or posted.
"""

from __future__ import annotations

import platform
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from espec_burnin import GITHUB_REPO, __version__

NEW_ISSUE_URL = f"https://github.com/{GITHUB_REPO}/issues/new"

# GitHub and browsers both give up well before 8 kB of URL. Stay clear of it and
# keep the full text on the clipboard regardless.
MAX_URL_CHARS = 6000
LOG_TAIL_LINES = 25

KINDS = {
    "bug": ("Bug", "bug"),
    "improvement": ("Improvement", "enhancement"),
}


def log_path() -> Path:
    return Path.home() / ".espec-burn-in" / "espec-burn-in.log"


def redact(text: str) -> str:
    """Reduce anything under the user's home directory to ``~``.

    Reports go to a public repository, and a Windows home path carries the
    account name.
    """
    if not text:
        return text
    home = str(Path.home())
    out = text.replace(home, "~").replace(home.replace("\\", "/"), "~")
    if "\\" in home:                      # Windows paths appear escaped in logs
        out = out.replace(home.replace("\\", "\\\\"), "~")
    return out


def read_log_tail(lines: int = LOG_TAIL_LINES, path: Path | None = None) -> list[str]:
    """The last few log lines, which is where an error will have landed."""
    try:
        text = (path or log_path()).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [redact(line) for line in text.strip().splitlines()[-lines:]]


def environment() -> dict[str, str]:
    qt = "not available"
    try:
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import qVersion

        qt = f"PySide6 {pyside_version} / Qt {qVersion()}"
    except Exception:  # noqa: BLE001 - a report must never fail to build
        pass

    return {
        "Program version": __version__,
        "Installed as": "packaged build" if getattr(sys, "frozen", False)
                        else "run from source",
        "Operating system": platform.platform(),
        "Machine": platform.machine(),
        "Python": platform.python_version(),
        "Qt": qt,
    }


@dataclass
class Report:
    """A report as it will be posted."""

    kind: str = "bug"
    summary: str = ""
    description: str = ""
    context: dict[str, str] = field(default_factory=dict)
    trail: list[str] = field(default_factory=list)
    log_tail: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def label(self) -> str:
        return KINDS.get(self.kind, KINDS["bug"])[1]

    @property
    def title(self) -> str:
        kind_name = KINDS.get(self.kind, KINDS["bug"])[0]
        text = self.summary.strip() or (
            "Unexpected behaviour" if self.kind == "bug" else "Suggested improvement"
        )
        return f"[{kind_name}] {text}"

    def body(self, include_log: bool = True) -> str:
        is_bug = self.kind == "bug"
        parts: list[str] = []

        parts.append("### What happened" if is_bug else "### What would be better")
        parts.append(self.description.strip() or "_(not described)_")

        if is_bug:
            parts.append("### What I expected instead")
            parts.append("_(fill in if it helps)_")

        # What they did, before what the program was: the steps are usually
        # the answer to "how do I reproduce this", and nobody should have to
        # remember them.
        if self.trail:
            parts.append("### What was done just before this")
            parts.append("```\n" + "\n".join(self.trail) + "\n```")
        elif is_bug:
            parts.append("### Steps to reproduce")
            parts.append("1. \n2. \n3. ")

        rows = {**environment(), **self.context}
        # The header and the rows must be one block: a blank line between them
        # stops GitHub rendering it as a table at all.
        table = ["| | |", "| --- | --- |"] + [
            f"| {key} | {redact(str(value))} |"
            for key, value in rows.items() if value != ""
        ]
        parts.append("### Program state when this was reported")
        parts.append("\n".join(table))

        if include_log and self.log_tail:
            parts.append("### Last lines of the log")
            parts.append("```\n" + "\n".join(self.log_tail) + "\n```")

        parts.append(
            "<sub>Reported from the program on "
            f"{self.created_at.strftime('%d %b %Y %H:%M')}.</sub>"
        )
        return "\n\n".join(parts)


def split_edited(text: str) -> tuple[str, str]:
    """A report the user has edited, back into a title and a body.

    The preview is editable, so what is posted is whatever it says rather than
    what the program would have written. The first non-empty line is the title.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip():
            return line.strip(), "\n".join(lines[index + 1:]).strip()
    return "", ""


def issue_url(report: Report, base: str = NEW_ISSUE_URL,
              edited: str | None = None) -> tuple[str, bool]:
    """The pre-filled URL, and whether anything had to be left out of it.

    A long log tail will not survive a query string, so it is dropped rather
    than producing a URL the browser silently truncates. The caller is expected
    to put the whole report on the clipboard either way.
    """
    if edited is not None:
        title, body = split_edited(edited)
        url = base + "?" + urllib.parse.urlencode({
            "title": title or report.title, "labels": report.label, "body": body,
        })
        if len(url) <= MAX_URL_CHARS:
            return url, False
        # Too long once edited: the text is the user's, so nothing is dropped
        # out of the middle of it. Send the title and let them paste the body.
        return base + "?" + urllib.parse.urlencode({
            "title": title or report.title,
            "labels": report.label,
            "body": "_(too long for the address bar - paste from the clipboard)_",
        }), True

    for include_log in (True, False):
        body = report.body(include_log=include_log)
        url = base + "?" + urllib.parse.urlencode({
            "title": report.title,
            "labels": report.label,
            "body": body,
        })
        if len(url) <= MAX_URL_CHARS:
            return url, not include_log

    # Still too long: keep the head of the body rather than nothing.
    body = report.body(include_log=False)
    while len(body) > 500:
        body = body[: int(len(body) * 0.8)]
        url = base + "?" + urllib.parse.urlencode({
            "title": report.title,
            "labels": report.label,
            "body": body + "\n\n_(truncated — the full report is on your clipboard)_",
        })
        if len(url) <= MAX_URL_CHARS:
            return url, True
    return base + "?" + urllib.parse.urlencode({
        "title": report.title, "labels": report.label,
    }), True
