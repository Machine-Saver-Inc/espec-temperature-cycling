"""Watlow F4 controller driver (Modbus RTU over serial).

Register map and serial settings are the ones proven on the bench in
``Negative_Oven.ipynb``.  Do not re-derive the register numbers from the Watlow
manual: the manual numbers registers from 1 while minimalmodbus sends
zero-based addresses, so the two disagree by one.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import minimalmodbus
import serial

log = logging.getLogger(__name__)

# --- Verified constants -----------------------------------------------------
SLAVE_ADDRESS = 201
BAUDRATE = 19200
BYTESIZE = 8
PARITY = serial.PARITY_NONE
STOPBITS = 1

REG_PROCESS_VALUE = 100   # chamber air temperature, tenths degC, function code 3
REG_SETPOINT = 300        # commanded setpoint, tenths degC

DECIMALS = 1              # values are in tenths of a degree
READ_TIMEOUT_S = 0.35     # notebook used 0.10, which mistakes a slow reply for a dead chamber
RETRIES = 3

# Any reading outside this band means we are not talking to a temperature
# controller, whatever answered.
PLAUSIBLE_MIN_C = -80.0
PLAUSIBLE_MAX_C = 200.0


class ChamberError(Exception):
    """Communication with the chamber failed."""


@dataclass(frozen=True)
class Reading:
    temperature_c: float
    at: float


class WatlowF4:
    """Thread-safe synchronous driver.

    All temperatures cross this boundary as degrees Celsius floats, positive or
    negative.  The signed/tenths encoding is handled by minimalmodbus via
    ``signed=True`` and ``number_of_decimals=1`` -- never by hand.
    """

    def __init__(
        self,
        port: str,
        slave_address: int = SLAVE_ADDRESS,
        *,
        close_port_after_each_call: bool = True,
        timeout: float = READ_TIMEOUT_S,
        write_functioncode: int = 16,
    ) -> None:
        self.port = port
        self.write_functioncode = write_functioncode
        self._lock = threading.Lock()

        self._inst = minimalmodbus.Instrument(
            port=port, slaveaddress=slave_address, mode=minimalmodbus.MODE_RTU
        )
        self._inst.serial.baudrate = BAUDRATE
        self._inst.serial.bytesize = BYTESIZE
        self._inst.serial.parity = PARITY
        self._inst.serial.stopbits = STOPBITS
        self._inst.serial.timeout = timeout
        self._inst.close_port_after_each_call = close_port_after_each_call
        self._inst.clear_buffers_before_each_transaction = True

    # -- reads ---------------------------------------------------------------
    def read_temperature(self, retries: int = RETRIES) -> float:
        """Chamber air temperature in degrees Celsius.

        Correctly returns negative temperatures.  The notebook divided the raw
        register by 10 unconditionally, which reports -20 degC as 6533.6 degC.
        """
        last: Exception | None = None
        for attempt in range(retries):
            try:
                with self._lock:
                    value = self._inst.read_register(
                        REG_PROCESS_VALUE, DECIMALS, functioncode=3, signed=True
                    )
                if not PLAUSIBLE_MIN_C <= value <= PLAUSIBLE_MAX_C:
                    raise ChamberError(f"implausible reading {value} degC")
                return value
            except Exception as exc:  # noqa: BLE001 - re-raised below
                last = exc
                log.debug("read attempt %d failed: %s", attempt + 1, exc)
                time.sleep(0.05)
        raise ChamberError(f"could not read temperature on {self.port}: {last}") from last

    # -- writes --------------------------------------------------------------
    def write_setpoint(self, celsius: float, retries: int = RETRIES) -> None:
        """Command a setpoint in degrees Celsius, positive or negative.

        The notebook's helper computed ``65536 - abs(t) * 10``, which turns a
        positive setpoint into its negative.  Passing ``signed=True`` handles
        both signs.
        """
        last: Exception | None = None
        for attempt in range(retries):
            try:
                with self._lock:
                    self._inst.write_register(
                        REG_SETPOINT,
                        celsius,
                        DECIMALS,
                        functioncode=self.write_functioncode,
                        signed=True,
                    )
                return
            except Exception as exc:  # noqa: BLE001 - re-raised below
                last = exc
                log.debug("write attempt %d failed: %s", attempt + 1, exc)
                time.sleep(0.05)
        raise ChamberError(f"could not set setpoint on {self.port}: {last}") from last

    def read_setpoint(self, retries: int = RETRIES) -> float:
        last: Exception | None = None
        for _attempt in range(retries):
            try:
                with self._lock:
                    return self._inst.read_register(
                        REG_SETPOINT, DECIMALS, functioncode=3, signed=True
                    )
            except Exception as exc:  # noqa: BLE001 - re-raised below
                last = exc
                time.sleep(0.05)
        raise ChamberError(f"could not read setpoint on {self.port}: {last}") from last

    def close(self) -> None:
        try:
            self._inst.serial.close()
        except Exception:  # noqa: BLE001 - closing is best effort
            pass
