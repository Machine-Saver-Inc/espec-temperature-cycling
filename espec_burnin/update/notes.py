"""What a release body says to somebody already running the program.

A release page serves two people who want opposite things. A first-time visitor
needs the download and the install steps; somebody who pressed **What's new**
inside the program has already installed it and wants to know what is
different. The body is composed for both, changes first and install second,
separated by a horizontal rule.

This takes the first half. Qt-free, so what the window will show can be
asserted without building one.
"""

from __future__ import annotations

import re

# A Markdown horizontal rule on a line of its own: --- or *** or ___, three or
# more, optionally spaced. What follows the first one is the install section.
RULE = re.compile(r"^[ \t]*(?:-[ \t]*){3,}$|^[ \t]*(?:\*[ \t]*){3,}$"
                  r"|^[ \t]*(?:_[ \t]*){3,}$", re.M)

# "## What's new in 1.4.0" duplicates the window title.
LEAD_HEADING = re.compile(r"\A[ \t]*#{1,6}[ \t]*What's new[^\n]*\n+", re.I)


def what_changed(body: str) -> str:
    """The part of a release body that is about the change, not the download.

    Everything up to the first horizontal rule, without the heading the window
    title already carries. A body with no rule is returned whole -- a release
    written by hand should still show, and showing too much is better than
    showing nothing.
    """
    if not body or not body.strip():
        return ""
    found = RULE.search(body)
    text = body[: found.start()] if found else body
    text = LEAD_HEADING.sub("", text, count=1)
    return text.strip()
