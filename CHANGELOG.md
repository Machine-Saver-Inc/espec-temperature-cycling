# Changelog

## [0.9.0]

### Added
- **Report a problem**, bottom-left on every screen, with a journal-and-bug
  icon. It gathers the version, the screen that was open, the chamber and port,
  the controller settings and safety limits, what a run was doing at the time,
  and the last lines of the log, then opens a GitHub issue with all of it filled
  in. Bug and improvement produce different templates and different labels.
- The whole report is shown before anything is sent and copied to the clipboard
  as well, so it survives a browser that will not open or a log too long for the
  address bar.
- Paths under the user's home folder are shortened to `~` before a report is
  shown or posted, since the repository is public.

### Fixed
- CI now also runs on Python 3.10, which `pyproject.toml` has always claimed to
  support. A backslash inside an f-string expression — valid only from 3.12 —
  had already slipped in.

### Added (testing)
- Smoke tests that build every screen and the report dialog. They immediately
  caught a null icon: `QIcon` takes a pixmap, not a `QImage`, and the button
  would have shipped with no icon and no error.


## [0.8.0]

### Added
- **The chamber speed test now writes every sample to disk as it happens.** It
  kept them in memory, so stopping a measurement — or losing power — threw away
  the evidence of the stall it was run to find. Each sample is flushed to
  `measurement.csv` under `Documents/Espec Burn-In/Chamber tests/`, with the
  measured temperature, the rate, the 5 °C band, and whether that sample counted
  as progress. A stall is a run of samples that counted as none.
- The results screen has **Open the measurement data**, and says explicitly that
  a stopped test still kept everything up to that point.
- `tools/analyse_measurement.py` turns a `measurement.csv` or a saved
  `profile.json` into a band-by-band breakdown: minutes spent in each band,
  average rate, where progress stopped, and the slowest band.


## [0.7.0]

### Changed
- **A chamber is now the thing measurements belong to (#1).** The speed test
  is identified by the chamber's model and serial number, the way the floor
  identifies it, with the test's own name as a second section underneath. One
  chamber holds as many named tests as you like, and the tests already saved
  for it are listed while you set a new one up.
- Model and serial remember what has been used before and offer it back;
  connecting through the same USB adapter recognises the chamber with no
  typing, because the adapter's serial number is already how a port is
  remembered.
- A recipe is checked against a measurement of *that* chamber rather than
  whichever profile happened to be saved first.
- Runs record the chamber they ran on, in `run.json` and at the top of the
  report.

### Compatibility
- Profiles saved by 0.3.0 to 0.6.0 are still read; they simply have no chamber
  against them until they are measured again.


## [0.6.0]

### Fixed
- **A failed update check reported "you are up to date" (#2).** The check
  returned the same empty answer whether nothing newer existed or the request
  had failed, and the window turned that into a reassurance. Running 0.4.0 with
  0.5.0 published, *Check for updates* said 0.4.0 was newest. A check now
  reports one of three things — an update, genuinely current, or could not
  reach GitHub — and the last of those shows what went wrong (no internet, a
  proxy, an unverifiable certificate, a rate limit) with the underlying error
  so it can be reported. The home screen says so too rather than showing a
  stale timestamp.
- **The chamber speed test could drive past the safety limits (#1).** It wrote
  setpoints straight to the driver, bypassing the clamp every run obeys, and
  the setup screen offered -40 °C and +105 °C against a clamp of -25/+85. The
  measurement is now clamped like a run, the targets are bounded by the limits
  in Settings, and the confirmation quotes what will actually be commanded.

### Changed
- The update check waits 15 s rather than 5 and retries once, so one slow or
  dropped response on a corporate link no longer reads as a failure.
- If the system certificate store rejects the connection, the check retries
  with a bundled CA list. The system store is still tried first, because a
  proxy that intercepts TLS installs its own CA there.

### Changed
- The setpoint write function code is documented as confirmed rather than
  assumed. The notebook that drove the real chamber passed no `functioncode`,
  so minimalmodbus used its default of 16 and that write worked; 16 is what the
  program has always sent. Function code 6 stays selectable for a different
  controller.


## [0.5.0]

### Added
- The README now shows the program: screenshots of the home screen, port
  selection, run setup, a run in progress, a failure, the settings and a
  measured chamber profile, woven into a step-by-step walkthrough of a real job.
- `tools/screenshots.py` regenerates every image offscreen, so they are
  reproducible on any machine with no display and no chamber, and cannot drift
  from the release by hand.
- Tests assert the README leads with the download, shows at least four screens,
  and that every image it references exists and is committed.

### Fixed
- The selected serial port rendered as a blank highlighted bar. Its text used
  the inactive-selection colour when the list did not have focus, so the port
  the user had just picked was unreadable. Found by looking at the generated
  screenshot.
- Hint text under form fields is now styled as secondary rather than body text.


## [0.4.0]

### Added
- **Update now actually updates.** It downloads the file for the platform,
  verifies it against the release's `SHA256SUMS`, and installs it: the Windows
  installer runs silently and the program reopens, an AppImage replaces itself
  and restarts, and a `.deb` shows the one apt command since the program will
  not ask for root. Previously the button only opened the release page.
- A download whose checksum does not match, or whose checksum list cannot be
  fetched, is refused rather than installed, and nothing is changed.
- The home screen shows the installed version and when the program last managed
  to check for updates, with a **Check for updates** button. A chamber PC with
  no internet is never told about a release, so the version needs to be
  readable without one.
- `espec-burn-in --version` prints the version from a command line.


## [0.3.0]

### Added
- **Chamber capability test.** Drives the chamber to each extreme and records
  how fast it actually moved, in 5 °C bands, in both directions, along with the
  coldest and hottest it reached. Saved as a named profile that records how the
  chamber was loaded, since an empty chamber with closed ports is the best case
  rather than the operating case.
- The recipe screen checks the recipe against the measured profile and warns
  when a ramp is faster than the chamber can follow or a setpoint is beyond what
  it reached, with a button to fill in the measured times.

### Fixed
- Guaranteed soak could stretch a run without end: a chamber that never reached
  the hold temperature never started the dwell timer, so the run had no finish.
  There is now a maximum extension (50% by default, configurable, 0 to disable)
  after which the run is failed with the reason recorded.


## [0.2.0]

### Added
- Every value is editable. A Settings screen exposes the connection (address,
  baud, framing, timeout, retries, write function code), run behaviour (sample
  interval, comms grace) and safety limits (setpoint clamp, runaway
  thresholds). Widening the clamp asks for confirmation.
- Run length can be given as a total time instead of a cycle count; 48 hours is
  a default, not a fixture.
- Cooling and heating ramps are set independently, since chambers rarely cool
  as fast as they heat.
- Hold tolerance, the temperature the chamber returns to, and the assumed
  starting temperature are editable on the recipe screen.

### Changed
- A port held by another program now says so, instead of "check the COM port",
  and on Linux names the process holding it. Missing ports, permission
  problems and a silent chamber are told apart and each get their own steps.
- Serial ports are opened exclusively where the platform allows, so a second
  program is refused rather than quietly corrupting the conversation.


## [Unreleased]

### Added
- Watlow F4 driver over Modbus RTU with correct signed handling for negative
  and positive setpoints and readings.
- Chamber simulator: a real Modbus RTU slave on a pseudo-terminal with a thermal
  lag model, so a 48-hour run can be exercised in seconds.
- Profile engine: setpoint as a pure function of elapsed time, with guaranteed
  soak so a lagging chamber stretches the run instead of shortening the dwell.
- Port discovery with auto-detect, remembered by USB adapter serial number
  rather than by COM name, and on-screen guidance when no ports exist.
- On-screen troubleshooting when the chamber stops answering, without abandoning
  the run.
- CSV logging flushed every sample, resumable run state, and a self-contained
  HTML report.
- Update checking against GitHub Releases, suppressed during a run.
- Windows installer (Inno Setup), Debian package and AppImage, each with a
  desktop icon.

### Fixed
- Unsigned read from register 100 reported −20 °C as 6533.6 °C.
- `convert_oven()` turned a positive setpoint into its negative.
