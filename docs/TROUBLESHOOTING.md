# Troubleshooting

## No serial ports found

1. Check the USB-to-serial adapter is plugged into this computer.
2. Check the serial cable runs from that adapter to the communications port on
   the chamber.
3. **Windows:** open Device Manager and look under *Ports (COM & LPT)*. A yellow
   warning triangle, or the adapter listed under *Other devices*, means the
   driver is not installed — install the driver for your adapter brand (FTDI,
   Prolific, Silicon Labs or CH340).
4. **Linux:** run `ls /dev/ttyUSB* /dev/ttyACM*`. If nothing is listed the
   adapter is not being detected; `dmesg | tail` right after plugging it in will
   say why.
5. **Linux:** if the port exists but cannot be opened, add your user to the
   `dialout` group with `sudo usermod -aG dialout $USER`, then log out and back
   in.

## Not getting a temperature from the chamber

These are the steps the program shows on screen, cheapest and most likely first.

1. **Is the chamber switched on?** The Watlow F4 display on the front of the
   chamber should be lit and showing a temperature. If it is dark, turn the
   chamber's main power on and give the controller about ten seconds to start.
2. **Is a fault showing?** If the F4 display is flashing an alarm or error,
   clear it at the controller before going further. If the chamber's separate
   over-temperature limit controller has tripped, it has to be reset on that
   limit controller — the F4 cannot clear it, and the chamber will not heat or
   cool until it is.
3. **Check the cable.** The serial cable should be firmly seated at both ends:
   the communications port on the chamber, and the USB adapter on this computer.
4. **Check the port.** Confirm the port still exists — Device Manager under
   *Ports (COM & LPT)* on Windows, `ls /dev/ttyUSB*` on Linux. If the adapter
   has been unplugged and replugged the name may have changed; **Find it for me**
   will re-detect it.
5. **Is anything else using the port?** Chamber vendor software, a terminal
   program such as PuTTY or Tera Term, or a second copy of this program will
   hold the port open and lock this one out. Close them.
6. **Check the controller's communication settings.** They should read
   address 201, 19200 baud, 8 data bits, no parity, 1 stop bit. These rarely
   change on their own, but a controller that has been factory reset will be
   back at its defaults.

### What happens to the run meanwhile

Nothing is abandoned. The program keeps retrying underneath the panel and the
panel closes itself the moment a reading comes back. Because the profile is
computed from wall-clock time, the run works out where the cycle should be by
now and carries on. Gaps are marked in `run.csv` and listed in the report.

If communication does not come back within 15 minutes, the run is marked failed,
the reason is recorded, and the log is closed cleanly so the partial data is
still usable.

## The program says the temperature is not following the setpoint

The chamber has been more than 15 °C away from target for over 10 minutes during
a dwell. Usually one of:

- The chamber door is open or not sealing.
- The load in the chamber is far larger than it can pull down.
- A refrigeration or heater fault the F4 has not reported as an alarm.
- The commanded ramp is faster than the chamber can follow. Lower the ramp rate
  on the recipe screen; a ramp the chamber cannot hold becomes a step change and
  the recorded profile stops meaning anything.

## The run stopped because the computer slept

The program inhibits sleep while a run is active, but a forced sleep, a lid
close on some laptops, or a power cut will still end it. Reopen the program: it
offers to resume the interrupted run and picks the cycle back up from
wall-clock time.

## Log file

`~/.espec-burn-in/espec-burn-in.log` on both platforms.
