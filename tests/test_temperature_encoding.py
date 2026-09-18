"""Regression tests for the two sign bugs in Negative_Oven.ipynb.

These run the production driver against a real Modbus RTU slave over a
pseudo-terminal, so they exercise the actual wire encoding rather than
re-implementing the arithmetic in the test.
"""

from __future__ import annotations

import sys

import pytest

from espec_burnin.hardware.f4 import WatlowF4
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
        driver = WatlowF4(sim.port, sim.slave_address, close_port_after_each_call=False)
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
    from espec_burnin.hardware.f4 import ChamberError

    sim, driver = chamber
    sim.temperature_c = 250.0
    with pytest.raises(ChamberError):
        driver.read_temperature()


@needs_pty
def test_write_function_code_6_also_works(chamber):
    """Some F4s want function code 6 rather than minimalmodbus's default 16."""
    sim, _ = chamber
    driver = WatlowF4(
        sim.port, sim.slave_address, close_port_after_each_call=False, write_functioncode=6
    )
    driver.write_setpoint(-20.0)
    assert sim.setpoint_c == pytest.approx(-20.0)
    driver.close()


@pytest.mark.parametrize("celsius", [-25.0, -20.0, 0.0, 80.0, 85.0])
def test_encoding_helpers_are_symmetric(celsius):
    assert from_signed_register(to_signed_register(celsius)) == pytest.approx(celsius)
