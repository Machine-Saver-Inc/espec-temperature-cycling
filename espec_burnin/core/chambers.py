"""The chambers this computer has worked with.

A measured profile belongs to a *chamber*, not to a free-text label. The
chamber is identified by its model and serial number the way it is identified
on the shop floor, and the tests run against it hang underneath.

The link to hardware is the USB adapter's own serial number, which is already
how a port is remembered. Plug the same adapter in and the chamber it belongs
to is recognised without anyone typing anything.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


def chambers_path() -> Path:
    return Path.home() / ".espec-burn-in" / "chambers.json"


def slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-")
    return cleaned or "unknown"


@dataclass
class Chamber:
    """One physical chamber, as the shop floor identifies it."""

    model: str = ""
    serial: str = ""
    adapter_serial: str | None = None    # the USB adapter it was last reached through
    last_port: str | None = None
    first_seen: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    last_used: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def key(self) -> str:
        """Stable identity used for folder names and lookups."""
        return f"{slug(self.model)}__{slug(self.serial)}"

    @property
    def label(self) -> str:
        if self.model and self.serial:
            return f"{self.model} — Serial {self.serial}"
        return self.model or self.serial or "Unnamed chamber"

    @property
    def is_named(self) -> bool:
        return bool(self.model.strip() and self.serial.strip())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Chamber:
        fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (data or {}).items() if k in fields})


def load_chambers() -> list[Chamber]:
    """Every chamber known to this computer, most recently used first."""
    try:
        raw = json.loads(chambers_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    chambers = [Chamber.from_dict(item) for item in raw if isinstance(item, dict)]
    chambers = [c for c in chambers if c.is_named]
    return sorted(chambers, key=lambda c: c.last_used, reverse=True)


def save_chamber(chamber: Chamber) -> list[Chamber]:
    """Add or update a chamber. Matching is by model and serial, not by name."""
    if not chamber.is_named:
        return load_chambers()

    chambers = load_chambers()
    chamber.last_used = datetime.now().isoformat(timespec="seconds")

    for index, existing in enumerate(chambers):
        if existing.key == chamber.key:
            chamber.first_seen = existing.first_seen
            chambers[index] = chamber
            break
    else:
        chambers.insert(0, chamber)

    path = chambers_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps([c.to_dict() for c in chambers], indent=2),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # the registry is a convenience, never load-bearing
    return chambers


def find_by_adapter(adapter_serial: str | None) -> Chamber | None:
    """Which chamber was last reached through this USB adapter."""
    if not adapter_serial:
        return None
    for chamber in load_chambers():
        if chamber.adapter_serial == adapter_serial:
            return chamber
    return None


def find(model: str, serial: str) -> Chamber | None:
    wanted = Chamber(model=model, serial=serial).key
    for chamber in load_chambers():
        if chamber.key == wanted:
            return chamber
    return None


def known_models() -> list[str]:
    seen: dict[str, None] = {}
    for chamber in load_chambers():
        seen.setdefault(chamber.model, None)
    return list(seen)


def serials_for_model(model: str) -> list[str]:
    return [c.serial for c in load_chambers() if c.model == model]
