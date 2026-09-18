"""Serial port discovery, ranking and auto-detection."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

from serial.tools import list_ports

from espec_burnin.hardware.f4 import SLAVE_ADDRESS, ChamberError, WatlowF4

log = logging.getLogger(__name__)

# USB-to-serial chipsets we expect to find a chamber behind.
KNOWN_USB_SERIAL_VIDS = {
    0x0403: "FTDI",
    0x067B: "Prolific",
    0x10C4: "Silicon Labs",
    0x1A86: "CH340/CH341",
    0x2341: "Arduino",
}


@dataclass(frozen=True)
class PortInfo:
    device: str            # "COM3" or "/dev/ttyUSB0"
    description: str       # "USB Serial Port (FTDI FT232R)"
    serial_number: str | None   # stable across re-plugging; COM numbers are not
    vid: int | None
    pid: int | None

    @property
    def is_known_usb_serial(self) -> bool:
        return self.vid in KNOWN_USB_SERIAL_VIDS

    @property
    def is_probably_bluetooth(self) -> bool:
        """Windows lists Bluetooth virtual COM ports; they are never the chamber."""
        return "bluetooth" in self.description.lower()

    @property
    def label(self) -> str:
        return f"{self.device} — {self.description}"


def list_serial_ports() -> list[PortInfo]:
    """Every serial port, best candidate first.

    Known USB-serial adapters sort to the top and Bluetooth virtual ports to the
    bottom, because picking a Bluetooth port is the single most common mistake.
    """
    ports = [
        PortInfo(
            device=p.device,
            description=p.description or "Serial port",
            serial_number=p.serial_number,
            vid=p.vid,
            pid=p.pid,
        )
        for p in list_ports.comports()
    ]
    return sorted(
        ports,
        key=lambda p: (p.is_probably_bluetooth, not p.is_known_usb_serial, p.device),
    )


def find_port_by_serial_number(serial_number: str) -> PortInfo | None:
    """Re-find a remembered adapter wherever it landed.

    COM numbers move when the adapter is plugged into a different socket; the
    adapter's own serial number does not.
    """
    if not serial_number:
        return None
    for port in list_serial_ports():
        if port.serial_number == serial_number:
            return port
    return None


def probe_port(device: str, slave_address: int = SLAVE_ADDRESS) -> float | None:
    """Return the temperature if a chamber answers on this port, else None."""
    driver = None
    try:
        driver = WatlowF4(device, slave_address, timeout=0.3)
        return driver.read_temperature(retries=2)
    except (ChamberError, OSError, Exception) as exc:  # noqa: BLE001 - probing
        log.debug("no chamber on %s: %s", device, exc)
        return None
    finally:
        if driver is not None:
            driver.close()


def autodetect(slave_address: int = SLAVE_ADDRESS) -> tuple[PortInfo, float] | None:
    """Walk candidate ports and return the first that answers plausibly."""
    for port in list_serial_ports():
        if port.is_probably_bluetooth:
            continue
        temperature = probe_port(port.device, slave_address)
        if temperature is not None:
            return port, temperature
    return None


def linux_dialout_hint() -> str | None:
    """On Linux, tell the user how to fix the usual permission problem."""
    if sys.platform.startswith("linux"):
        return "sudo usermod -aG dialout $USER   # then log out and back in"
    return None
