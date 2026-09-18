# Changelog

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
