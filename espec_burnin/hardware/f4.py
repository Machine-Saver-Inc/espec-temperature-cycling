"""Watlow F4 controller driver (Modbus RTU over serial).

Register map and serial defaults are the ones proven on the bench in
``Negative_Oven.ipynb``.  Do not re-derive the register numbers from the Watlow
manual: the manual numbers registers from 1 while minimalmodbus sends
zero-based addresses, so the two disagree by one.

Everything except the register numbers is configurable, because a controller
that has been reconfigured or factory reset will not match the defaults.
"""

from __future__ import annotations

import errno
import logging
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass

import minimalmodbus
import serial

from espec_burnin.hardware.errors import (
    ChamberError,
    ImplausibleReadingError,
    NoReplyError,
    PortBusyError,
    PortMissingError,
    PortPermissionError,
)

log = logging.getLogger(__name__)

# --- Register map: the one thing that is not configurable -------------------
REG_PROCESS_VALUE = 100   # chamber air temperature, tenths degC, function code 3
REG_SETPOINT = 300        # commanded setpoint, tenths degC
DECIMALS = 1              # values are in tenths of a degree

PARITY_CHOICES = {"None": serial.PARITY_NONE,
                  "Even": serial.PARITY_EVEN,
                  "Odd": serial.PARITY_ODD}


@dataclass
class ConnectionSettings:
    """Serial and Modbus settings. All of it editable under Settings."""

    slave_address: int = 201
    baudrate: int = 19200
    bytesize: int = 8
    parity: str = "None"          # key into PARITY_CHOICES
    stopbits: int = 1
    timeout_s: float = 0.35       # the notebook used 0.10, too tight to be safe
    retries: int = 3
    write_functioncode: int = 16  # confirmed on our chamber; 6 is the fallback
    close_port_after_each_call: bool = True
    plausible_min_c: float = -80.0
    plausible_max_c: float = 200.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ConnectionSettings:
        fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (data or {}).items() if k in fields})


def port_holders(device: str) -> tuple[str, ...]:
    """Best effort: which processes hold this port open.

    Linux only, by walking /proc. Naming the program that has the port is far
    more useful than telling someone to go and find it.
    """
    if not sys.platform.startswith("linux"):
        return ()
    holders: list[str] = []
    try:
        target = os.path.realpath(device)
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            fd_dir = f"/proc/{pid}/fd"
            try:
                for fd in os.listdir(fd_dir):
                    if os.path.realpath(os.path.join(fd_dir, fd)) == target:
                        with open(f"/proc/{pid}/comm") as handle:
                            holders.append(f"{handle.read().strip()} (pid {pid})")
                        break
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                continue
    except OSError:
        return ()
    return tuple(dict.fromkeys(holders))


def classify_open_failure(exc: Exception, device: str) -> ChamberError:
    """Turn a pyserial open failure into something the user can act on.

    Windows reports a busy port as access-denied. Linux reports a missing group
    the same way, so the two platforms need different readings of the same
    errno.
    """
    text = str(exc)
    code = getattr(exc, "errno", None)
    if code is None:
        cause = exc.__cause__ or exc.__context__
        code = getattr(cause, "errno", None)

    lowered = text.lower()
    missing = (
        code == errno.ENOENT
        or "no such file" in lowered
        or "cannot find the file" in lowered
        or "filenotfounderror" in lowered
    )
    if missing:
        return PortMissingError(port=device, detail=text)

    denied = (
        code in (errno.EACCES, errno.EBUSY, errno.EAGAIN)
        or "access is denied" in lowered
        or "permissionerror" in lowered
        or "resource busy" in lowered
        or "device or resource busy" in lowered
    )
    if denied:
        if sys.platform == "win32":
            # Windows opens serial ports exclusively, so access-denied here
            # means something else already has it.
            return PortBusyError(port=device, detail=text)
        holders = port_holders(device)
        if holders or code in (errno.EBUSY, errno.EAGAIN):
            return PortBusyError(port=device, detail=text, holders=holders)
        return PortPermissionError(port=device, detail=text)

    return NoReplyError(port=device, detail=text)


class WatlowF4:
    """Thread-safe synchronous driver.

    Temperatures cross this boundary as degrees Celsius floats, positive or
    negative.  The signed/tenths encoding is handled by minimalmodbus via
    ``signed=True`` and ``number_of_decimals=1`` -- never by hand.
    """

    def __init__(self, port: str, settings: ConnectionSettings | None = None) -> None:
        self.port = port
        self.settings = settings or ConnectionSettings()
        self._lock = threading.Lock()

        try:
            self._inst = minimalmodbus.Instrument(
                port=port,
                slaveaddress=self.settings.slave_address,
                mode=minimalmodbus.MODE_RTU,
            )
        except Exception as exc:  # noqa: BLE001 - classified below
            raise classify_open_failure(exc, port) from exc

        s = self._inst.serial
        s.baudrate = self.settings.baudrate
        s.bytesize = self.settings.bytesize
        s.parity = PARITY_CHOICES.get(self.settings.parity, serial.PARITY_NONE)
        s.stopbits = self.settings.stopbits
        s.timeout = self.settings.timeout_s
        # Take the port exclusively where the platform supports it, so a second
        # program is refused rather than silently corrupting the conversation.
        try:
            s.exclusive = True
        except (AttributeError, ValueError):
            pass

        self._inst.close_port_after_each_call = self.settings.close_port_after_each_call
        self._inst.clear_buffers_before_each_transaction = True

    # -- reads ---------------------------------------------------------------
    def read_temperature(self, retries: int | None = None) -> float:
        """Chamber air temperature in degrees Celsius.

        Correctly returns negative temperatures.  The original notebook divided
        the raw register by 10 unconditionally, reporting -20 degC as 6533.6.
        """
        last: Exception | None = None
        for _attempt in range(retries if retries is not None else self.settings.retries):
            try:
                with self._lock:
                    value = self._inst.read_register(
                        REG_PROCESS_VALUE, DECIMALS, functioncode=3, signed=True
                    )
            except Exception as exc:  # noqa: BLE001 - classified below
                last = exc
                log.debug("read failed: %s", exc)
                time.sleep(0.05)
                continue

            if not (self.settings.plausible_min_c <= value <= self.settings.plausible_max_c):
                raise ImplausibleReadingError(
                    port=self.port, detail=f"reply decoded to {value} degC"
                )
            return value

        raise self._classify(last)

    def read_setpoint(self, retries: int | None = None) -> float:
        last: Exception | None = None
        for _attempt in range(retries if retries is not None else self.settings.retries):
            try:
                with self._lock:
                    return self._inst.read_register(
                        REG_SETPOINT, DECIMALS, functioncode=3, signed=True
                    )
            except Exception as exc:  # noqa: BLE001 - classified below
                last = exc
                time.sleep(0.05)
        raise self._classify(last)

    # -- writes --------------------------------------------------------------
    def write_setpoint(self, celsius: float, retries: int | None = None) -> None:
        """Command a setpoint in degrees Celsius, positive or negative.

        The notebook's helper computed ``65536 - abs(t) * 10``, which turned a
        positive setpoint into its negative.  ``signed=True`` handles both.
        """
        last: Exception | None = None
        for _attempt in range(retries if retries is not None else self.settings.retries):
            try:
                with self._lock:
                    self._inst.write_register(
                        REG_SETPOINT,
                        celsius,
                        DECIMALS,
                        functioncode=self.settings.write_functioncode,
                        signed=True,
                    )
                return
            except Exception as exc:  # noqa: BLE001 - classified below
                last = exc
                time.sleep(0.05)
        raise self._classify(last)

    def _classify(self, exc: Exception | None) -> ChamberError:
        if exc is None:
            return NoReplyError(port=self.port)
        if isinstance(exc, ChamberError):
            return exc
        if isinstance(exc, (serial.SerialException, OSError)):
            return classify_open_failure(exc, self.port)
        # minimalmodbus raises its own NoResponseError / InvalidResponseError
        return NoReplyError(port=self.port, detail=str(exc))

    def close(self) -> None:
        try:
            self._inst.serial.close()
        except Exception:  # noqa: BLE001 - closing is best effort
            pass
