"""One line-drawn mark per action, in the colour of the text beside it.

Drawn here rather than shipped as files because they are a handful of paths,
and because every one has to be tinted to match the button it sits on - a
fixed-colour icon is unreadable on a machine set to dark.

All are stroked on the same 24-unit grid with the same weight, so they read as
one set at the 16px they are used at.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

log = logging.getLogger(__name__)

SIZE = 16

# Stroked paths unless the name is in FILLED below.
GLYPHS = {
    "back":      "M15 5 L8 12 L15 19",
    "forward":   "M9 5 L16 12 L9 19",
    "start":     "M7 4 L20 12 L7 20 Z",
    "stop":      "M6 6 h12 v12 h-12 Z",
    "save":      "M5 13 l4 4 L19 7",
    "folder":    "M4 18 v-11 h5 l2 2 h9 v9 Z",
    "speed":     "M5.6 18.4 A9 9 0 1 1 18.4 18.4 M12 12 L17 7",
    # Sliders, not a gear: eight spokes and a small circle collapse into an
    # asterisk at 16px, which is what shipped the first time.
    "settings":  ("M3.5 6.5 h17 M3.5 17.5 h17 "
                  "M8.5 3 v7 M15.5 14 v7"),
    "refresh":   "M20 12 a8 8 0 1 1 -2.4 -5.7 M20 4 v4 h-4",
    "download":  "M12 4 v10 M8 11 l4 4 4 -4 M5 19 h14",
    "notes":     "M7 3.5 h7 l4 4 v13 h-11 Z M14 3.5 v4 h4 M9.5 12 h7 M9.5 16 h7",
    "later":     "M20 12 a8 8 0 1 1 -16 0 a8 8 0 1 1 16 0 M12 7 v5.5 l3.5 2",
    "search":    "M17 11 a6 6 0 1 1 -12 0 a6 6 0 1 1 12 0 M15.4 15.4 L20 20",
    "connect":   "M9 3 v4.5 M15 3 v4.5 M7 7.5 h10 v3 a5 5 0 0 1 -10 0 Z M12 15.5 v5.5",
    "copy":      "M9 9 h9 v10 h-9 Z M6 15 H5 V5 h9 v1",
    "cancel":    "M6.5 6.5 L17.5 17.5 M17.5 6.5 L6.5 17.5",
    "discard":   "M5.5 7 h13 M9.5 7 V4.5 h5 V7 M7 7 l1 13 h8 l1 -13",
    "edit":      "M4 20 l1.2 -4.2 L16 5 l3 3 L8.2 18.8 Z",
    "open":      "M14 4 h6 v6 M20 4 L11.5 12.5 M17 13.5 V20 H4 V6 h6.5",
}
FILLED = {"start", "stop"}


def _svg(name: str, colour: str) -> str:
    path = GLYPHS[name]
    if name in FILLED:
        paint = f'fill="{colour}" stroke="none"'
    else:
        paint = (f'fill="none" stroke="{colour}" stroke-width="1.9" '
                 f'stroke-linecap="round" stroke-linejoin="round"')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="24" height="24"><path d="{path}" {paint}/></svg>'
    )


def icon(name: str, colour: str = "#1a1a1a", size: int = SIZE) -> QIcon:
    """The named mark, tinted, or an empty icon if anything goes wrong.

    A missing icon is never worth failing a screen over, but it is worth a log
    line: a button that silently loses its mark looks like a design choice.
    """
    if name not in GLYPHS:
        log.warning("no icon called %r", name)
        return QIcon()
    try:
        from PySide6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(QByteArray(_svg(name, colour).encode("utf-8")))
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
