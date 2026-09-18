"""Remembered settings.

The port is remembered by the adapter's USB serial number rather than by name:
COM numbers move when the adapter is plugged into a different socket, the
adapter's serial number does not.
"""

from __future__ import annotations

import json
from pathlib import Path

from espec_burnin.core.profile import Recipe


def settings_path() -> Path:
    return Path.home() / ".espec-burn-in" / "settings.json"


DEFAULTS = {
    "adapter_serial": None,
    "last_port": None,
    "operator": "",
    "check_for_updates": True,
    "recipe": Recipe().to_dict(),
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(settings_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return data


def save(data: dict) -> None:
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # settings are a convenience, never load-bearing
