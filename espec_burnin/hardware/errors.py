"""Failure kinds the user can actually act on.

The driver raises these instead of leaking ``serial.SerialException``, because
"could not open port" covers three completely different situations that need
three different answers from the person standing at the chamber.
"""

from __future__ import annotations


class ChamberError(Exception):
    """Base class. `headline` and `steps` drive what the UI shows."""

    headline = "Cannot talk to the chamber"
    steps: tuple[str, ...] = ()

    def __init__(self, message: str = "", *, port: str = "", detail: str = "") -> None:
        super().__init__(message or self.headline)
        self.port = port
        self.detail = detail


class PortBusyError(ChamberError):
    """The port exists but another program holds it open."""

    headline = "The COM port is being used by another program"
    steps = (
        "Close any chamber or instrument software supplied with the Espec.",
        "Close any terminal program — PuTTY, Tera Term, RealTerm, the Arduino "
        "Serial Monitor.",
        "Check this program is not already running in another window; only one "
        "copy can use the chamber.",
        "If you cannot find it, unplugging the USB adapter and plugging it back "
        "in releases the port.",
    )

    def __init__(self, message: str = "", *, port: str = "", detail: str = "",
                 holders: tuple[str, ...] = ()) -> None:
        super().__init__(message, port=port, detail=detail)
        self.holders = holders


class PortPermissionError(ChamberError):
    """The port exists but this user account may not open it."""

    headline = "This computer will not let the program open the port"
    steps = (
        "On Linux, your user needs to be in the 'dialout' group:\n"
        "    sudo usermod -aG dialout $USER\n"
        "then log out and back in.",
        "On Windows, try running the program as the same user that installed the "
        "USB adapter driver.",
    )


class PortMissingError(ChamberError):
    """The port has gone away, usually an unplugged adapter."""

    headline = "That COM port is no longer there"
    steps = (
        "Check the USB-to-serial adapter is still plugged in.",
        "If it was unplugged and plugged back in, the port name may have changed "
        "— use 'Find it for me' to pick it up again.",
        "On Windows, confirm it appears in Device Manager under Ports (COM & LPT).",
    )


class NoReplyError(ChamberError):
    """The port opened fine, but nothing answered on it."""

    headline = "Not getting a temperature from the chamber"
    steps = (
        "Is the chamber switched on? The Watlow F4 display should be lit and "
        "showing a temperature.",
        "Is a fault showing? Clear any alarm at the controller. If the separate "
        "over-temperature limit controller has tripped, it must be reset there.",
        "Check the serial cable is seated at both ends.",
        "Check you picked the right port — 'Find it for me' will test each one.",
        "Check the controller's settings match: address, baud rate, data bits, "
        "parity and stop bits, under Settings → Connection.",
    )


class ImplausibleReadingError(NoReplyError):
    """Something answered, but not with a temperature."""

    headline = "Something answered, but it is not the chamber"
    steps = (
        "The device on this port replied with a value that is not a plausible "
        "temperature. It is probably a different instrument.",
        "Use 'Find it for me' to test the other ports.",
        "If the chamber really is on this port, check the address and baud rate "
        "under Settings → Connection.",
    )
