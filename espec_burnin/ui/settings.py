"""Remembered settings.

The port is remembered by the adapter's USB serial number rather than by name:
COM numbers move when the adapter is plugged into a different socket, the
adapter's serial number does not.
"""

from __future__ import annotations

import json
from pathlib import Path

from espec_burnin.core.profile import Recipe
from espec_burnin.core.run_controller import RunTuning
from espec_burnin.hardware.f4 import ConnectionSettings


def settings_path() -> Path:
    return Path.home() / ".espec-burn-in" / "settings.json"


def defaults() -> dict:
    return {
        "adapter_serial": None,
        "last_port": None,
        "operator": "",
        "check_for_updates": True,
        "recipe": Recipe().to_dict(),
        "connection": ConnectionSettings().to_dict(),
        "tuning": RunTuning().to_dict(),
    }


def load() -> dict:
    data = defaults()
    try:
        stored = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key].update(value)
        else:
            data[key] = value
    return data


def save(data: dict) -> None:
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # settings are a convenience, never load-bearing


def connection_from(data: dict) -> ConnectionSettings:
    return ConnectionSettings.from_dict(data.get("connection", {}))


def tuning_from(data: dict) -> RunTuning:
    return RunTuning.from_dict(data.get("tuning", {}))


def recipe_from(data: dict) -> Recipe:
    try:
        return Recipe.from_dict(data.get("recipe", {}))
    except (TypeError, ValueError):
        return Recipe()
