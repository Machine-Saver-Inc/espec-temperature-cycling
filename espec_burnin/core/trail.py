"""What the operator did, in order, so a report can say how they got there.

A report that arrives with only a description and a state table leaves the
question "what did you press?" to a round trip. The answer is on the machine
already: the program knows which screens were opened and which buttons were
pressed, and none of it is worth asking a person to remember.

Only labels and screen names are kept - no values typed, no paths - so the
trail carries nothing that would be a surprise to post to a public repository.

Qt-free: the interface records into it, the report reads out of it, and the
tests use neither.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

# Enough to cover getting to the screen the problem is on, short enough that it
# never dominates a report or pushes it past the length a URL can carry.
KEPT = 40
SHOWN = 15


@dataclass(frozen=True)
class Step:
    at: datetime
    what: str

    def __str__(self) -> str:
        return f"{self.at.strftime('%H:%M:%S')}  {self.what}"


class Trail:
    """The last few things that happened, oldest first."""

    def __init__(self, kept: int = KEPT) -> None:
        # The interface records from the GUI thread and a worker may record a
        # finished run from another, so the deque is guarded.
        self._steps: deque[Step] = deque(maxlen=kept)
        self._lock = threading.Lock()

    def record(self, what: str, at: datetime | None = None) -> None:
        text = " ".join(str(what).split())
        if not text:
            return
        with self._lock:
            # A button pressed five times in a row is one line with a count,
            # not five lines pushing everything else out of the trail.
            if self._steps and self._steps[-1].what.split(" ×")[0] == text:
                last = self._steps.pop()
                times = int(last.what.split(" ×")[1]) + 1 if " ×" in last.what else 2
                self._steps.append(Step(last.at, f"{text} ×{times}"))
                return
            self._steps.append(Step(at or datetime.now(), text))

    def opened(self, screen: str) -> None:
        self.record(f"opened {screen}")

    def pressed(self, label: str) -> None:
        self.record(f"pressed {label}")

    def happened(self, event: str) -> None:
        self.record(event)

    def steps(self, limit: int = SHOWN) -> list[Step]:
        with self._lock:
            return list(self._steps)[-limit:]

    def lines(self, limit: int = SHOWN) -> list[str]:
        return [str(step) for step in self.steps(limit)]

    def clear(self) -> None:
        with self._lock:
            self._steps.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._steps)


# One per running program. The interface records into this; the report reads it.
TRAIL = Trail()
