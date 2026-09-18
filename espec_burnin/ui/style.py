"""One stylesheet, light and dark, so the app doesn't read as a default Qt form."""

from __future__ import annotations

ACCENT = "#2f6feb"
GOOD = "#1a7f37"
WARN = "#9a6700"
BAD = "#b4232c"

STYLESHEET = f"""
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
"""
