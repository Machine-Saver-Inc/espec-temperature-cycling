"""Keep the computer awake for the duration of a run.

A machine that sleeps at hour 12 leaves the chamber holding whatever setpoint it
was last given, for the next 36 hours.
"""

from __future__ import annotations

import logging
import subprocess
import sys

log = logging.getLogger(__name__)

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


class KeepAwake:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None

    def __enter__(self) -> KeepAwake:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def start(self) -> None:
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.kernel32.SetThreadExecutionState(
                    _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
                )
            except Exception as exc:  # noqa: BLE001 - best effort
                log.warning("could not inhibit sleep: %s", exc)
        elif sys.platform.startswith("linux"):
            try:
                self._process = subprocess.Popen(
                    [
                        "systemd-inhibit",
                        "--what=sleep:idle",
                        "--why=Temperature cycling run in progress",
                        "--mode=block",
                        "sleep",
                        "infinity",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (OSError, FileNotFoundError) as exc:
                log.warning("could not inhibit sleep: %s", exc)

    def stop(self) -> None:
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
            except Exception:  # noqa: BLE001 - best effort
                pass
        if self._process is not None:
            self._process.terminate()
            self._process = None
