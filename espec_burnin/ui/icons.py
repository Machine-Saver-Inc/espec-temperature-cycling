"""The mark on a button, from Lucide.

Every icon in this program comes from **Lucide** (https://lucide.dev) - the set
shadcn/ui is built on - vendored into `resources/icons/` from `lucide-static`
and licensed ISC. Hand-drawn glyphs were tried first and two of them shipped
illegible at 16px; a maintained set drawn on one grid by people who do this for
a living is a better default than anything drawn here in an afternoon.

The file name is the name a button asks for, so the application never mentions
a Lucide name: `icon("back")`, not `icon("arrow-left")`. That indirection is
what lets the mark for an idea change without touching every screen.

Every mark is stroked in `currentColor`, which is substituted for the colour of
the text beside it - a fixed-colour icon is invisible on a machine set to dark.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

log = logging.getLogger(__name__)

SIZE = 16
ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"
LIBRARY = "Lucide"


@lru_cache(maxsize=1)
def names() -> tuple[str, ...]:
    """Every mark available, by the name a button asks for."""
    if not ICON_DIR.is_dir():
        log.error("no icon folder at %s", ICON_DIR)
        return ()
    return tuple(sorted(p.stem for p in ICON_DIR.glob("*.svg")))


def icon(name: str, colour: str = "#1a1a1a", size: int = SIZE) -> QIcon:
    """The named mark, tinted, or an empty icon if anything goes wrong.

    A missing icon is never worth failing a screen over, but it is worth a log
    line: a button that silently loses its mark looks like a design choice.
    """
    source = ICON_DIR / f"{name}.svg"
    if not source.is_file():
        log.warning("no icon called %r; the set holds %s", name, ", ".join(names()))
        return QIcon()
    try:
        from PySide6.QtSvg import QSvgRenderer

        raw = source.read_text(encoding="utf-8").replace("currentColor", colour)
        renderer = QSvgRenderer(QByteArray(raw.encode("utf-8")))
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter)
        painter.end()
        # QIcon(QImage) yields a null icon and no error - it has to be a pixmap.
        return QIcon(QPixmap.fromImage(image))
    except Exception as exc:  # noqa: BLE001
        log.warning("could not render the %r icon: %s", name, exc)
        return QIcon()
