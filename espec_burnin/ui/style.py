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
    # palette(mid) is too faint for a border on some Windows themes and too
    # loud on others, so the edge is stated rather than borrowed.
    edge = "#5a6570" if dark else "#bcc3cb"
    sunk = "#2b3138" if dark else "#e9edf1"
    muted = "#2f4470" if dark else "#a9c1ef"
    muted_text = "#8fa3c4" if dark else "#f2f6fd"
    focus_ring = "#9db8ee" if dark else "#14357f"
    danger_wash = "#3a1f22" if dark else "#fdf0f1"
    return f"""
QWidget {{ font-size: 14px; }}
QLabel#Title {{ font-size: 26px; font-weight: 600; }}
QLabel#Subtitle {{ font-size: 15px; color: palette(mid); }}
QLabel#BigTemperature {{ font-size: 76px; font-weight: 300; }}
QLabel#Target {{ font-size: 18px; color: palette(mid); }}
QLabel#StatusGood {{ color: {GOOD}; font-weight: 600; }}
QLabel#StatusWarn {{ color: {WARN}; font-weight: 600; }}
QLabel#StatusBad {{ color: {BAD}; font-weight: 600; }}
/* Buttons ---------------------------------------------------------------
   Setting padding and a radius without also setting a border and a background
   makes Qt drop the native button look entirely, which is how every secondary
   button in the program came to render as bare text with nothing to click.
   Each role is now described in full, including the states. */
QPushButton {{
    background: palette(base);
    color: palette(text);
    border: 1px solid {edge};
    border-radius: 6px;
    padding: 8px 14px;
    min-height: 18px;
    /* Mark first, then the words. On a button sized to its text this changes
       nothing; in a column of equal-width buttons it is what lines the marks
       up instead of scattering them by label length. */
    text-align: left;
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:pressed {{ background: {sunk}; }}
QPushButton:disabled {{
    color: palette(mid); border-color: {edge}; background: transparent;
}}
QPushButton:focus {{ border: 2px solid {ACCENT}; padding: 7px 13px; }}

QPushButton#Primary {{
    background: {ACCENT}; color: white; font-weight: 600;
    padding: 13px 26px; font-size: 16px; border: 1px solid {ACCENT};
    border-radius: 7px;
}}
QPushButton#Primary:hover {{ background: #2560d0; border-color: #2560d0; }}
QPushButton#Primary:pressed {{ background: #1f52b4; border-color: #1f52b4; }}
/* Muted accent rather than grey: a disabled primary should read as "not yet",
   not as a dead control. */
QPushButton#Primary:disabled {{
    background: {muted}; border-color: {muted}; color: {muted_text};
}}
QPushButton#Primary:focus {{ border: 2px solid {focus_ring}; padding: 12px 25px; }}

QPushButton#Danger {{ color: {BAD}; border-color: {edge}; }}
QPushButton#Danger:hover {{ border-color: {BAD}; color: {BAD}; background: {danger_wash}; }}

QPushButton#Report {{ padding: 6px 12px; }}
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
