"""Regression tests for the two sign bugs in Negative_Oven.ipynb.

These run the production driver against a real Modbus RTU slave over a
pseudo-terminal, so they exercise the actual wire encoding rather than
re-implementing the arithmetic in the test.
"""

from __future__ import annotations

import sys

import pytest

from espec_burnin.hardware.f4 import ConnectionSettings, WatlowF4
from espec_burnin.hardware.simulator import (
    ChamberSimulator,
    from_signed_register,
    to_signed_register,
)

# Only the tests that open a pseudo-terminal are POSIX-only. The encoding
# tests below run everywhere, including Windows, which is where the program
# actually ships.
needs_pty = pytest.mark.skipif(
    sys.platform == "win32", reason="the pty-backed simulator is POSIX only"
)

CYCLE_TEMPERATURES = [-20.0, -10.5, -0.1, 0.0, 23.6, 45.0, 80.0]


@pytest.fixture
def chamber():
    with ChamberSimulator() as sim:
        driver = WatlowF4(sim.port, ConnectionSettings(slave_address=sim.slave_address,
                                          close_port_after_each_call=False))
        yield sim, driver
        driver.close()


@pytest.mark.parametrize("celsius", CYCLE_TEMPERATURES)
@needs_pty
def test_setpoint_round_trips_with_correct_sign(chamber, celsius):
    sim, driver = chamber
    driver.write_setpoint(celsius)
    assert sim.setpoint_c == pytest.approx(celsius, abs=0.05)
    assert driver.read_setpoint() == pytest.approx(celsius, abs=0.05)


@pytest.mark.parametrize("celsius", CYCLE_TEMPERATURES)
@needs_pty
def test_temperature_reads_back_with_correct_sign(chamber, celsius):
    sim, driver = chamber
    sim.temperature_c = celsius
    assert driver.read_temperature() == pytest.approx(celsius, abs=0.05)


@needs_pty
def test_notebook_unsigned_read_bug_is_fixed(chamber):
    """Bug 1: `read_register(100, functioncode=3) / 10` reports -20 degC as 6533.6."""
    sim, driver = chamber
    sim.temperature_c = -20.0

    raw = sim._read_register(100)
    assert raw == 65336
    assert raw / 10 == pytest.approx(6533.6)  # what the notebook would have reported

    assert driver.read_temperature() == pytest.approx(-20.0)


@needs_pty
def test_notebook_positive_setpoint_bug_is_fixed(chamber):
    """Bug 2: `convert_oven(t) = 65536 - abs(t)*10` turns +65 degC into -65 degC."""
    sim, driver = chamber

    def convert_oven(negative):  # verbatim from the notebook
        return 65536 - (abs(negative) * 10)

    assert from_signed_register(convert_oven(65)) == pytest.approx(-65.0)

    driver.write_setpoint(65.0)
    assert sim.setpoint_c == pytest.approx(65.0)


@needs_pty
def test_implausible_reading_is_rejected(chamber):
    """A reading outside the plausible band must raise, not be logged as data.

    Note the register cannot itself hold 6533.6: that number only ever existed
    because the notebook divided a signed value as if it were unsigned.
    """
    from espec_burnin.hardware.errors import ChamberError

    sim, driver = chamber
    sim.temperature_c = 250.0
    with pytest.raises(ChamberError):
        driver.read_temperature()


@needs_pty
def test_write_function_code_6_also_works(chamber):
    """Some F4s want function code 6 rather than minimalmodbus's default 16."""
    sim, _ = chamber
    driver = WatlowF4(
        sim.port,
        ConnectionSettings(
            slave_address=sim.slave_address,
            close_port_after_each_call=False,
            write_functioncode=6,
        ),
    )
    driver.write_setpoint(-20.0)
    assert sim.setpoint_c == pytest.approx(-20.0)
    driver.close()


@pytest.mark.parametrize("celsius", [-25.0, -20.0, 0.0, 80.0, 85.0])
def test_encoding_helpers_are_symmetric(celsius):
    assert from_signed_register(to_signed_register(celsius)) == pytest.approx(celsius)


# --- failure classification -------------------------------------------------
# "could not open port" covers three different situations that need three
# different answers from whoever is standing at the chamber.

import errno as _errno  # noqa: E402

import serial as _serial  # noqa: E402

from espec_burnin.hardware.errors import (  # noqa: E402
    PortBusyError,
    PortMissingError,
    PortPermissionError,
)
from espec_burnin.hardware.f4 import classify_open_failure  # noqa: E402


def _win(message):
    return _serial.SerialException(message)


def _posix(errno_value, message):
    exc = _serial.SerialException(message)
    exc.errno = errno_value
    return exc


def test_windows_access_denied_means_the_port_is_busy(monkeypatch):
    """Windows opens serial ports exclusively, so access-denied is contention."""
    monkeypatch.setattr(sys, "platform", "win32")
    err = classify_open_failure(
        _win("could not open port 'COM3': PermissionError(13, 'Access is denied.')"),
        "COM3",
    )
    assert isinstance(err, PortBusyError)
    assert "another program" in err.headline


def test_missing_port_is_not_reported_as_busy(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    err = classify_open_failure(
        _win("could not open port 'COM9': FileNotFoundError(2, 'cannot find the file')"),
        "COM9",
    )
    assert isinstance(err, PortMissingError)


def test_linux_eacces_without_a_holder_is_a_permissions_problem(monkeypatch):
    """On Linux the same errno usually means the dialout group, not contention."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("espec_burnin.hardware.f4.port_holders", lambda device: ())
    err = classify_open_failure(
        _posix(_errno.EACCES, "Permission denied: '/dev/ttyUSB0'"), "/dev/ttyUSB0"
    )
    assert isinstance(err, PortPermissionError)
    assert "dialout" in " ".join(err.steps)


def test_linux_eacces_with_a_holder_names_the_program(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        "espec_burnin.hardware.f4.port_holders", lambda device: ("minicom (pid 991)",)
    )
    err = classify_open_failure(
        _posix(_errno.EACCES, "Permission denied: '/dev/ttyUSB0'"), "/dev/ttyUSB0"
    )
    assert isinstance(err, PortBusyError)
    assert err.holders == ("minicom (pid 991)",)


def test_linux_ebusy_is_busy_even_with_no_holder_found(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("espec_burnin.hardware.f4.port_holders", lambda device: ())
    err = classify_open_failure(
        _posix(_errno.EBUSY, "device or resource busy"), "/dev/ttyUSB0"
    )
    assert isinstance(err, PortBusyError)


def test_every_failure_kind_gives_the_user_something_to_do():
    for kind in (PortBusyError, PortMissingError, PortPermissionError):
        assert kind.steps, f"{kind.__name__} has no steps"
        assert kind.headline != PortBusyError.__mro__[1].headline or kind is PortBusyError
