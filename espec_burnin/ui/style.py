"""One stylesheet, light and dark, so the app doesn't read as a default Qt form.

The window surface stays the operating system's - a lab PC set to dark is set
that way for a reason - so colours here are either theme-independent or come in
a pair and are chosen at startup.
"""

from __future__ import annotations

ACCENT = "#2f6feb"
GOOD = "#1a7f37"
WARN = "#9a6700"
BAD = "#b4232c"

# The two ends of a cycle. Used only where cold and hot sit side by side and
# the colour is carrying which is which, never as decoration.
COLD = "#2b6a9b"
HOT = "#a35c1c"
COLD_DARK = "#6fb3e0"
HOT_DARK = "#d99a4e"


def ends(dark: bool = False) -> tuple[str, str]:
    """The cold and hot colours for the theme in use."""
    return (COLD_DARK, HOT_DARK) if dark else (COLD, HOT)


def build_stylesheet(dark: bool = False) -> str:
    cold, hot = ends(dark)
    return f"""
QWidget {{ font-size: 14px; }}
QLabel#Title {{ font-size: 26px; font-weight: 600; }}
QLabel#Subtitle {{ font-size: 15px; color: palette(mid); }}
QLabel#BigTemperature {{ font-size: 76px; font-weight: 300; }}
QLabel#Target {{ font-size: 18px; color: palette(mid); }}
QLabel#StatusGood {{ color: {GOOD}; font-weight: 600; }}
QLabel#StatusWarn {{ color: {WARN}; font-weight: 600; }}
QLabel#StatusBad {{ color: {BAD}; font-weight: 600; }}
QPushButton {{ padding: 9px 18px; border-radius: 6px; }}
QPushButton#Primary {{
    background: {ACCENT}; color: white; font-weight: 600;
    padding: 13px 26px; font-size: 16px; border: none; border-radius: 7px;
}}
QPushButton#Primary:hover {{ background: #2560d0; }}
QPushButton#Primary:disabled {{ background: palette(mid); color: palette(window); }}
QPushButton#Danger {{ color: {BAD}; }}
QPushButton#Report {{
    padding: 6px 12px; border: 1px solid palette(mid); border-radius: 6px;
    color: palette(text);
}}
QPushButton#Report:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QFrame#Card {{
    border: 1px solid palette(mid); border-radius: 9px; background: palette(base);
}}
QFrame#Banner {{
    border: 1px solid {ACCENT}; border-radius: 7px; background: palette(base);
}}
QListWidget {{ border: 1px solid palette(mid); border-radius: 7px; padding: 4px; }}
QListWidget::item {{ padding: 9px 8px; border-radius: 5px; }}
/* Without these the selected row uses the inactive palette when the list does
   not have focus, and the port the user just picked renders as a blank bar. */
QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
QListWidget::item:selected:!active {{ background: {ACCENT}; color: white; }}
QLabel#Hint {{ color: palette(mid); font-size: 12px; }}

/* -- grouping ----------------------------------------------------------
   A group is named on a hairline that runs the width of the form, with its
   fields inset underneath. Nine rounded cards with a shadow each would make
   every group look equally important, which is the opposite of grouping. */
QLabel#GroupName {{
    font-size: 13px; font-weight: 700; color: palette(text);
}}
QFrame#GroupRule {{ border: none; background: palette(mid); max-height: 1px; }}
QLabel#FieldLabel {{ color: palette(text); }}

/* The one bezel in the application: the cycle, which is what the page is
   actually for. Everything around it stays quiet so this reads as the
   instrument face. */
QFrame#Bezel {{
    border: 1px solid palette(mid); border-radius: 8px; background: palette(base);
}}
QLabel#ColdEnd {{ color: {cold}; font-weight: 700; font-size: 13px; }}
QLabel#HotEnd {{ color: {hot}; font-weight: 700; font-size: 13px; }}
QFrame#ColdRule {{ border: none; background: {cold}; max-height: 2px; }}
QFrame#HotRule {{ border: none; background: {hot}; max-height: 2px; }}
"""


STYLESHEET = build_stylesheet(False)
