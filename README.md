# Espec Burn-In

Temperature cycling for PCB burn-in. Drives an Espec chamber through a 48-hour
cycle between −20 °C and +80 °C via its **Watlow F4** controller over Modbus RTU,
to force board flexing and surface defects *before* the boards are soldered and
potted.

> **This program is not a safety system.** The chamber's independent
> over-temperature limit controller is the protective device. It must be set
> correctly and working before any unattended run.

## Download

### **[⬇ Get the latest release](https://github.com/Machine-Saver-Inc/espec-temperature-cycling/releases/latest)**

Nothing else is needed — Python, Qt and every dependency are bundled, so the
downloads are large (40–90 MB depending on platform) but there is nothing to
install afterwards. Each release page lists the exact size beside every file.

### Windows 10 / 11

1. Open the link above and download **`EspecBurnIn-Setup-<version>.exe`** from
   the *Assets* list at the bottom of the release.
2. Double-click it.
3. Windows will say **"Windows protected your PC"**. This is expected — the
   installer is not code-signed yet. Click **More info**, then **Run anyway**.
4. Click through the installer. It needs **no administrator rights** and
   installs for your user only. Leave *Create a desktop shortcut* ticked.
5. Launch **Espec Burn-In** from the desktop icon.

To update later, install the newer version over the top; settings and past
results are kept. The program also tells you when a new version exists.

### Debian / Ubuntu

Download **`espec-burn-in_<version>_amd64.deb`**, then:

```sh
sudo apt install ./espec-burn-in_<version>_amd64.deb
```

It appears in your applications menu as *Espec Burn-In*.

### Other Linux

Download **`EspecBurnIn-<version>-x86_64.AppImage`**, then:

```sh
chmod +x EspecBurnIn-*.AppImage
./EspecBurnIn-*.AppImage
```

### Linux: serial port permission

Opening a serial port needs group membership. If the program says it cannot
open the port:

```sh
sudo usermod -aG dialout $USER   # then log out and back in
```

### Checking what you downloaded

Every release includes `SHA256SUMS`. To verify:

```sh
sha256sum -c SHA256SUMS --ignore-missing
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

## The cycle

Nothing is fixed at 48 hours. The default preset is 12 cycles of 4 hours, which
works out at 48, but every value is editable on the recipe screen:

| Phase | Default | Setpoint |
| --- | --- | --- |
| Cool | 60 min | +80 → −20 °C (1.67 °C/min) |
| Hold cold | 60 min | −20 °C |
| Heat | 60 min | −20 → +80 °C (1.67 °C/min) |
| Hold hot | 60 min | +80 °C |

Set the run length either as a **number of cycles** or as a **total time** — ask
for 72 hours and the program works out the cycles and tells you the finish time.

Cooling and heating have separate ramp times, because a chamber rarely cools as
fast as it heats, and open cable entry ports widen the gap.

**Guaranteed soak** is on by default: a hold does not start counting until the
chamber is within tolerance of target, so a chamber running behind stretches the
run rather than shortening the time the boards spend at temperature.

## Measuring what the chamber can actually do

Whether the chamber can follow a commanded ramp depends on the load and on how
much heat leaks through the cable entry ports. **Measure the chamber's speed**
drives it to each extreme and records how fast it actually moved, in 5 °C bands.

Two things the measurement is careful about:

- **Speed is not constant.** A chamber that pulls down at 2.8 °C/min near +75
  may manage 0.3 °C/min over the last few degrees to −20, so most of the time is
  spent at the ends. Rates are recorded per band and integrated, never averaged.
- **An empty chamber is the best case, not your case.** Set the chamber up the
  way the real run will be — same boards, same fixtures, same cables through the
  ports — and say so when you save the profile. Measure it empty too if you want
  the comparison; they save separately, and recipes are checked against the
  loaded profile.

The test also records the coldest and hottest the chamber actually reached, so a
recipe asking for −20 °C in a chamber that only manages −17 is flagged before
you start rather than discovered at hour 30.

Once a profile exists, the recipe screen warns when a ramp is faster than the
chamber can follow, and **Use the measured times** fills in ramps that will
actually work.

## Settings

Everything the program relies on is editable under **Settings**, so a
reconfigured controller does not need a new build:

- **Connection** — controller address, baud rate, data bits, parity, stop bits,
  reply timeout, retries, setpoint write function code, and the range of
  readings treated as believable.
- **Run behaviour** — sample interval, how small a setpoint change is worth
  sending, and how long the chamber may stay unreachable before a run is failed.
- **Safety limits** — the hard clamp on commanded setpoints, and the runaway
  detection thresholds. Widening the clamp asks for confirmation.

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
