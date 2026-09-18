# Changelog

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
