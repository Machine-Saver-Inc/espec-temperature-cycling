# Watlow F4 protocol notes

Everything here is taken from `Negative_Oven.ipynb`, which was confirmed working
against the real chamber, plus the corrections needed to make it work for
negative *and* positive temperatures.

## Connection

| Setting | Value |
| --- | --- |
| Library | `minimalmodbus` over `pyserial`, `MODE_RTU` |
| Slave address | **201** |
| Baud / framing | **19200, 8N1** |
| `close_port_after_each_call` | `True` on Windows, may be `False` on Linux |
| `clear_buffers_before_each_transaction` | `True` |
| Timeout | 0.35 s with 3 retries |

The notebook used `timeout = 0.10`. That is tight enough that one slow reply
looks like a dead chamber, which on a 48-hour unattended run is the difference
between a logged hiccup and a failed test.

## Registers

| Register | Meaning | Function code |
| --- | --- | --- |
| `100` | Process value — chamber air temperature, tenths °C | 3 |
| `300` | Setpoint, tenths °C | 16 (some F4s want 6) |

**Do not re-derive these numbers from the Watlow F4 manual.** The manual numbers
registers from 1 while minimalmodbus sends zero-based addresses, so the manual
and these will disagree by one. 100 and 300 are the values proven on the bench.

## Two bugs inherited from the notebook

Both are covered by regression tests in
`tests/test_temperature_encoding.py`, run against the simulator on every push.

### 1. The read was unsigned

```python
oven.read_register(100, functioncode=3) / 10      # WRONG
```

The F4 returns temperature as a signed 16-bit value. At −20 °C the register
holds `65336`, and that line reports **6533.6 °C**. Every reading in the cold
half of the cycle would be garbage — which is the half this program exists for.

### 2. The write helper only handled negatives

```python
def convert_oven(negative):                        # WRONG for positives
    return 65536 - (abs(negative) * 10)
```

`convert_oven(65)` returns `64886`, which the F4 reads as **−65 °C**. Handing it
a positive setpoint commands the opposite sign.

## The correct form

Stop converting by hand. `minimalmodbus` handles both the sign and the implied
decimal place:

```python
temp_c = oven.read_register(100, 1, functioncode=3, signed=True)   # −20.0, 23.6
oven.write_register(300, setpoint_c, 1, signed=True)               # either sign
```

`espec_burnin/hardware/f4.py` is the only place in the codebase that touches
these registers.

## Why the profile runs in software

The chamber is left in plain static-setpoint mode and the program ramps the
setpoint itself, once a second.

- Only registers 100 and 300 are proven. The F4's internal profile programming
  is a much larger register surface nobody here has tested, and getting it wrong
  wastes a 48-hour run.
- The log becomes trustworthy: the program knows the commanded setpoint at every
  sample because it computed it, rather than inferring what the controller
  decided to do.
- It ports. Any controller that accepts a setpoint over Modbus can be added
  without rewriting the cycle logic.

The cost is that the PC is part of the run. If it sleeps or crashes, the F4
holds its last setpoint. Hence the sleep inhibitor, the resume-on-launch
prompt, and the rule that every run ends by commanding the chamber back to
25 °C.

## Still to confirm on the bench

- Whether this F4 accepts function code 16 for the setpoint write, or needs 6.
  `WatlowF4(..., write_functioncode=6)` switches it; both are tested.
- The exact key sequence to clear a fault on this chamber, for step 2 of the
  troubleshooting panel.
