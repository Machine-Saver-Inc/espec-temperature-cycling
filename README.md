# Espec Burn-In

Temperature cycling for PCB burn-in. Drives an Espec chamber through a 48-hour
cycle between −20 °C and +80 °C via its **Watlow F4** controller over Modbus RTU,
to force board flexing and surface defects *before* the boards are soldered and
potted.

> **This program is not a safety system.** The chamber's independent
> over-temperature limit controller is the protective device. It must be set
> correctly and working before any unattended run.

## Install

Download the file for your machine from the
[latest release](https://github.com/Machine-Saver-Inc/espec-temperature-cycling/releases/latest).
Nothing else is needed — Python and everything else is bundled.

| Platform | Download | Notes |
| --- | --- | --- |
| Windows 10/11 | `EspecBurnIn-Setup-<version>.exe` | Installs per-user, no administrator rights, adds a desktop icon |
| Debian / Ubuntu | `espec-burn-in_<version>_amd64.deb` | `sudo apt install ./espec-burn-in_<version>_amd64.deb` |
| Any Linux | `EspecBurnIn-<version>-x86_64.AppImage` | `chmod +x` it and run it |

The installers are not code-signed yet, so Windows shows
*"Windows protected your PC"*. Click **More info → Run anyway**.

On Linux, opening a serial port needs group membership:

```sh
sudo usermod -aG dialout $USER   # then log out and back in
```

## Running a burn-in

1. Open **Espec Burn-In** from the desktop icon.
2. **Start a burn-in run.** If the chamber is not connected yet, pick the port
   and press **Test connection** — or **Find it for me** to detect it. A green
   `Chamber is at 23.6 °C` is what confirms the right port, not the port name.
3. Type the board batch name and press **Continue**, then **Start run**.
4. Leave the computer on. The program keeps it awake for the duration.
5. When it finishes, **Open report**.

Results land in `Documents/Espec Burn-In/<batch> <date>/`:

| File | What it is |
| --- | --- |
| `run.csv` | every sample: timestamp, cycle, phase, setpoint, measured, comms status |
| `run.json` | the recipe and live position — this is what makes a crashed run resumable |
| `report.html` | a self-contained report with the chart and the verdict |

## The default cycle

12 cycles of 4 hours = 48 hours exactly.

| Phase | Duration | Setpoint |
| --- | --- | --- |
| Ramp down | 60 min | +80 → −20 °C (1.67 °C/min) |
| Cold dwell | 60 min | −20 °C |
| Ramp up | 60 min | −20 → +80 °C (1.67 °C/min) |
| Hot dwell | 60 min | +80 °C |

Cycle count, setpoints, ramp and dwell are all editable on the recipe screen.

**Guaranteed soak** is on by default: a dwell does not start counting until the
chamber is within ±2 °C of target, so a chamber running behind stretches the run
rather than shortening the time the boards spend at temperature.

## The chamber won't connect

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). The same steps appear in
the program itself when a run loses communication.

## Development

```sh
pip install -e ".[dev]"
pytest              # includes a full simulated 48-hour run
python -m espec_burnin
```

`espec_burnin/hardware/simulator.py` is a real Modbus RTU slave on a
pseudo-terminal — correct CRC, correct framing, correct signed encoding — so the
whole application can be exercised with no chamber. A 48-hour run takes a few
seconds under a virtual clock. That is deliberate: a 48-hour run cannot be the
development loop.

Protocol details and the two bugs inherited from the original notebook are in
[docs/F4-PROTOCOL.md](docs/F4-PROTOCOL.md).

## Releases

Tag and push; CI does the rest.

```sh
git tag v0.2.0 && git push origin v0.2.0
```

`.github/workflows/release.yml` builds on Windows and Linux, writes
`SHA256SUMS`, and publishes the release. The program checks that release feed on
launch and offers the update — never during a run.
