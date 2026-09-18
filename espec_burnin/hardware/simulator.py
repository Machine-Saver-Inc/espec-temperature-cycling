"""A fake Watlow F4 on a pseudo-terminal.

Speaks real Modbus RTU -- correct CRC, correct framing, correct signed
tenths-degree encoding -- so the production driver can be exercised end to end
with no chamber.  Also models thermal lag, so ramp-rate behaviour and the
"chamber cannot keep up" failure path can be tested.

Linux/macOS only (uses pty).  On Windows, use a com0com virtual pair or run the
tests under WSL; CI runs them on ubuntu-latest.
"""

from __future__ import annotations

import os
import pty
import threading

REG_PROCESS_VALUE = 100
REG_SETPOINT = 300


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def to_signed_register(celsius: float) -> int:
    """Degrees Celsius -> the 16-bit register value the F4 actually holds."""
    return int(round(celsius * 10)) & 0xFFFF


def from_signed_register(raw: int) -> float:
    """The 16-bit register value -> degrees Celsius."""
    if raw > 0x7FFF:
        raw -= 0x10000
    return raw / 10.0


class ChamberSimulator:
    """A Modbus RTU slave holding registers 100 and 300."""

    def __init__(
        self,
        slave_address: int = 201,
        start_temp_c: float = 23.6,
        *,
        max_ramp_c_per_min: float = 3.0,
        time_scale: float = 1.0,
    ) -> None:
        self.slave_address = slave_address
        self.temperature_c = start_temp_c
        self.setpoint_c = start_temp_c
        self.max_ramp_c_per_min = max_ramp_c_per_min
        self.time_scale = time_scale
        self.instant = True  # tests that only care about encoding skip the lag

        self._master_fd, self._slave_fd = pty.openpty()
        self.port = os.ttyname(self._slave_fd)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> ChamberSimulator:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def stop(self) -> None:
        self._stop.set()
        for fd in (self._master_fd, self._slave_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    # -- register access -----------------------------------------------------
    def _read_register(self, address: int) -> int:
        if address == REG_PROCESS_VALUE:
            return to_signed_register(self.temperature_c)
        if address == REG_SETPOINT:
            return to_signed_register(self.setpoint_c)
        raise KeyError(address)

    def _write_register(self, address: int, raw: int) -> None:
        if address != REG_SETPOINT:
            raise KeyError(address)
        self.setpoint_c = from_signed_register(raw)
        if self.instant:
            self.temperature_c = self.setpoint_c

    # -- wire protocol -------------------------------------------------------
    def _serve(self) -> None:
        buffer = b""
        while not self._stop.is_set():
            try:
                chunk = os.read(self._master_fd, 256)
            except OSError:
                return
            if not chunk:
                continue
            buffer += chunk
            frame, buffer = buffer, b""
            response = self._handle(frame)
            if response:
                try:
                    os.write(self._master_fd, response)
                except OSError:
                    return

    def _handle(self, frame: bytes) -> bytes | None:
        if len(frame) < 4:
            return None
        if crc16(frame[:-2]) != frame[-2:]:
            return None
        if frame[0] != self.slave_address:
            return None

        function = frame[1]
        try:
            if function == 3:  # read holding registers
                address = int.from_bytes(frame[2:4], "big")
                count = int.from_bytes(frame[4:6], "big")
                payload = b""
                for offset in range(count):
                    payload += self._read_register(address + offset).to_bytes(2, "big")
                body = bytes([self.slave_address, 3, len(payload)]) + payload

            elif function == 6:  # write single register
                address = int.from_bytes(frame[2:4], "big")
                self._write_register(address, int.from_bytes(frame[4:6], "big"))
                body = frame[:6]

            elif function == 16:  # write multiple registers
                address = int.from_bytes(frame[2:4], "big")
                count = int.from_bytes(frame[4:6], "big")
                for offset in range(count):
                    start = 7 + offset * 2
                    self._write_register(
                        address + offset, int.from_bytes(frame[start : start + 2], "big")
                    )
                body = frame[:6]

            else:
                return bytes([self.slave_address, function | 0x80, 0x01]) + crc16(
                    bytes([self.slave_address, function | 0x80, 0x01])
                )
        except KeyError:
            head = bytes([self.slave_address, function | 0x80, 0x02])
            return head + crc16(head)

        return body + crc16(body)

    # -- thermal model -------------------------------------------------------
    def advance(self, seconds: float) -> None:
        """Move the temperature toward the setpoint at a finite ramp rate."""
        self.instant = False
        limit = self.max_ramp_c_per_min * (seconds / 60.0)
        error = self.setpoint_c - self.temperature_c
        self.temperature_c += max(-limit, min(limit, error))
