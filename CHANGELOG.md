# Changelog

## [0.16.0]

**Back is on the left now**, where every other program puts it, and the button
that moves you forward is on the right. It was the other way round.

**Every button has a picture on it**, from a proper icon set rather than marks
drawn by hand, so the same idea looks the same here and in every other Machine
Saver program.

**The footer is on every screen**: report a problem on the left, who made the
program in the middle, and the version you are running - with the button to
check for a newer one - on the right. The version used to be on the first
screen only.

### Changed
- Navigation order reversed: `Back` left, the forward action right, on every
  screen. Built in one `action_bar` helper so six screens cannot disagree, and
  pinned by a test.
- Icons now come from **Lucide** (https://lucide.dev), the set shadcn/ui uses,
  vendored from `lucide-static` v1.47.0 into `resources/icons/` under its ISC
  licence. The name a button asks for is the file name, so no screen mentions a
  Lucide name. Hand-drawn glyphs are gone, including the journal-and-bug.
- The window footer carries the Machine Saver mark with *Created by Machine
  Saver Inc*, the installed version and last check, and *Check for updates* -
  on every screen rather than only on Home.

### Added
- A test that every button asks for a mark the library actually holds. It found
  one immediately: two buttons asked for `speed`, which is vendored as `gauge`,
  so they had been rendering nothing at all.
- A test that the same label always carries the same mark, so the vocabulary
  stays a vocabulary.

## [0.15.0]

**What's new now says what changed.** Pressing **What's new** used to show the
download and install instructions - for the program you were already running.
It now leads with a short, plain description of what is different in that
version, and the install steps follow underneath for anyone arriving for the
first time. Every past release has been given one of those descriptions too.

### Fixed
- **The release page led with install instructions instead of the changes**
  (issue #8). The release body was the install template, and the program's
  *What's new* button shows the release body, so somebody already running the
  program was handed a page telling them how to download it. The body is now
  composed from the plain-language summary at the top of this file's entry for
  that version, followed by the download section, with a link to the full list
  of changes.

### Added
- `tools/release_notes.py` composes the body, and three checks keep it honest:
  every version has a plain-language summary, none of those summaries use
  words that belong in a repository rather than at a chamber, and the release
  body leads with the changes rather than the download.
- Plain-language summaries written for all fourteen releases, so the rule is
  enforced everywhere rather than from here onwards.

## [0.14.0]

Nothing changes on screen in this version. The checks that used to be a list
someone had to remember are now part of the build itself, so a mistake that was
caught by eye before is caught before it can ship. One real fault turned up
while doing it: the stop icon was too small to read next to its label.

### Added
- **`tests/test_house_rules.py`** — the checks that used to live only in a
  checklist somebody had to remember. Each one failed a deliberate break before
  it was kept, because a guard that cannot fail is decoration:
  - buttons are built by the shared helper rather than by hand
  - a styled control that sets a corner radius also sets a border and a
    background, which is the exact mistake that made every secondary button
    render as bare text
  - every button role describes its hover, pressed and disabled appearance
  - every icon is legible at the size it ships at, in a light and a dark tint
  - the version has a `CHANGELOG` entry, and `release-notes.md` carries the
    `<version>` placeholder rather than a number
  - every issue named in the changelog has a test that names it too
  - `--version` works from the command line
- **The release workflow refuses a tag that is not on `main`**, which a timed-out
  push produced once, and **downloads its own published assets and verifies them
  against the checksums that went up with them**. Uploading is not the same as
  being downloadable, and the in-app updater refuses anything that does not
  match - better to find that in CI than on a bench.
- `python -m espec_burnin.ui.app --version` now works, so the version is
  readable without the installed shortcut.

### Fixed
- The stop icon was still only half the width of its grid and read as a speck
  beside its label. Found by the new legibility test rather than by eye.

## [0.13.0]

**Updating should work again.** The program could see a new version and then
fail to download it, because Windows only fetches the certificates it has
needed before and the download goes to a different address than the check.
Both now carry the certificates the program ships with, so neither depends on
what the machine happens to have collected.

**Every button now looks like a button** — a clear outline, and a small picture
on the left saying what it does. Several of them used to be plain words with
nothing to press.

**Reporting a problem now includes what you did just before it.** The screens
you opened and the buttons you pressed, in order, so you no longer have to
remember. You can edit the whole report before it is sent.

### Fixed
- **The update still failed on certificates, and the retry was the reason**
  (issue #7). A fallback to the bundled certificate list ran only *after* a
  failure, and only when that failure arrived as an SSL error. Windows fills
  its root store on demand rather than shipping it complete, so a host it has
  never fetched a root for is the ordinary case on a chamber PC - every such
  request paid for a doomed attempt first, and any failure that did not present
  as an SSL error skipped the retry altogether. There is no retry now: one
  connection carries the machine's own certificates *and* the ones we ship, so
  a company proxy's CA still works and a root Windows has never seen no longer
  needs a failure first.
- **Every button now looks like a button** (issue #6). Setting a padding and a
  corner radius without also setting a border and a background makes Qt discard
  the native button appearance, which is why most of them rendered as bare
  words with nothing to press. Primary, secondary and stop buttons are each
  described in full, including hover, pressed, focused and disabled, and every
  one carries a mark on the left. A disabled primary is a muted blue rather
  than grey, so it reads as "not yet" instead of broken.

### Added
- **A report now says what you did just before it** (issue #5). The program
  records which screens were opened and which buttons were pressed - labels
  only, never anything typed - and the last fifteen go into the report in
  place of three blank numbered lines. A button pressed repeatedly is one line
  with a count rather than fifteen identical ones.
- **The report is editable before it is sent.** What is posted is exactly what
  the preview says, so a detail can be added or taken out first. An edited
  report too long for the address bar sends its title and asks you to paste the
  rest, rather than cutting text somebody wrote.

## [0.12.0]

The setup screen no longer asks you to type the chamber's current temperature —
the program reads it when the run starts, so the first cooling ramp begins from
where the chamber actually is. The four serial settings are shown as one line,
`19200 8-N-1`, with a **Change** button for the rare chamber whose controller
has been altered.

### Removed
- **The assumed starting temperature is gone.** It asked the operator to type
  the chamber's current temperature so the first cooling ramp had somewhere to
  start. The program is connected and reading the chamber by the time a run
  begins, so it now reads the real temperature and starts the first ramp there.
  That removes a field, and makes the first ramp right rather than
  approximately right. A resumed run keeps the value it began with, since its
  first ramp is already behind it.
- **The Advanced section on the run screen.** With the guess removed it held
  one value, and one value does not earn a disclosure and a heading of its own.
  Where the chamber is left when a run ends now sits in *This run*, with the
  rest of the facts about this particular run.

### Changed
- **The serial link is one line: `19200 8-N-1`, with Change beside it.** Four
  dropdowns were stating a single fact. They are still there, and still saved,
  for the rare chamber whose controller has been reconfigured - they are just
  not the first thing on the page any more.
- **Retries per message** and the **setpoint write threshold** read as a
  sentence with a Change control, for the same reason: nobody setting up a
  chamber arrives with a view on how many times a failed message should be
  resent.

## [0.11.0]

**The setup screens are easier to read.** Every box now sits under a heading
that says what that section is for, instead of one long list where a batch
name, a temperature and a hold time all looked alike. The two ends of a cycle —
cold and hot — sit side by side so they can be compared, with the rate each
ramp works out to shown underneath it. Boxes are the width of what they hold,
so a temperature no longer stretches across the window.

### Changed
- **The setup screens are grouped.** Every input now sits under a named
  section that says what that section is for, instead of nine fields in one
  flat list where a board batch, a temperature and a hold time all looked
  alike. Choose the test is now *This run*, *One cycle*, *Reaching
  temperature* and *Advanced*; Settings splits into the serial link, the
  controller and believable readings, then reading the chamber and what ends a
  run, then setpoint limits and runaway detection. Grouping earns shorter
  labels - "Write function" inside *The controller* says as much as "Setpoint
  write function" did on its own.
- **The two ends of a cycle are set out side by side.** Six of the values on
  the run screen are cold/hot pairs, and as six separate rows that was
  invisible. Cold and hot are now columns - go to, taking, hold for - so they
  can be compared, and the asymmetry that matters (a chamber cools more slowly
  than it heats) can be read off the page instead of worked out.
- **The ramp rate is shown under the time that sets it.** It was buried in a
  sentence above the form; it is the figure the chamber actually has to
  achieve, so it belongs beside the box that decides it.
- **Inputs are the width of what they hold.** A two-digit temperature no
  longer stretches the width of the window, which made it read as a free-text
  field and put the stepper arrows a hand's width from the digits. Numbers are
  right-aligned in tabular figures so a column of readings lines up.
- The cold and hot colours are chosen for the theme in use, so they stay
  legible on a machine set to dark.

### Fixed
- The chamber speed setup screen crushed its own controls on a short window -
  the test-name box lost its descenders and the list of saved tests collapsed
  to a sliver. It scrolls now.

## [0.10.0]

**Updating no longer fails after telling you an update exists.** The download
now uses the same certificates the check does, and a failure is explained in
plain words instead of a line of code.

**The run report now shows where the chamber slowed down**, five degrees at a
time, for both cooling and heating — so a chamber that is slow all the way
through can be told apart from one that is fine until the last few degrees.
A speed test that simply ran out of time is no longer recorded as the chamber's
limit.

### Fixed
- **The update download failed on certificates even when the check succeeded**
  (issue #4). The check and the download talk to two different GitHub hosts,
  and Windows fills its root certificate store on demand, so a machine can
  verify one host and fail the other. Only the check had a fallback to a bundled
  certificate list, which is why the program could announce version 0.9.0 and
  then refuse to fetch it. Both now go through one connection helper: the
  computer's own certificate store first, so a company proxy still works, then
  the bundled list. A test fails the build if any part of the update code goes
  back to opening a connection of its own.
- A failed download now explains itself in the same plain words the check uses -
  "the secure connection to GitHub could not be verified, usually a company
  proxy or an out-of-date certificate store" - with the original error kept
  underneath so it can be reported. The dialog still offers the release page.
- The frozen build now explicitly carries the certificate list, so a packaging
  change cannot quietly remove the fallback.

### Added
- **The run report now says where the chamber slowed down** (issue #3).
  Alongside the coldest and hottest temperatures reached, cooling and heating
  each get a table of five-degree bands with the minutes and degrees per minute
  the chamber actually managed, and a sentence naming the typical rate, the
  point where it ran out of capacity and how far short of the setpoint it
  stopped. Averaged over a whole ramp those two cases look identical; split into
  bands they are obviously different problems.
- `tools/analyse_measurement.py` reads a burn-in `run.csv` as well as a speed
  test, so a run that has already happened - including one that was stopped
  early - can be looked at without repeating it.

### Changed
- **A speed test that ran out of time is no longer treated as the chamber's
  limit.** Each leg now records why it ended - reached, stalled, timed out or
  cancelled - and only a stall counts as evidence that the chamber cannot go
  further. A chamber reaches colder than the test had time to show; it simply
  takes longer, because every further degree is more work than the one before.
- Times projected beyond the measured range now continue the slowdown the test
  measured instead of holding the last rate flat, and are labelled as estimates.
  Held flat, a target far below anything measured looked as quick to reach as
  one just outside it, and a thirty-minute ramp looked adequate for it.

## [0.9.0]

**Report a problem** now sits in the bottom-left corner of every screen. It
fills in a report with everything usually asked for — the version, the screen
you were on, how the chamber is connected, what a run was doing — and opens
GitHub with it ready to post. You see all of it before anything is sent.

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

**A chamber speed test now saves everything as it goes.** Stopping one early —
or losing power — used to throw away the evidence of the very stall the test
was run to find. Every reading is written to disk as it happens.

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

**A speed test now belongs to a chamber**, named by its model and serial number
the way it is named on the floor, with the test's own name underneath. One
chamber can hold as many tests as you like — loaded, empty, whatever you need —
and connecting through the same adapter recognises the chamber without typing.

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

**A failed update check no longer says you are up to date.** If the program
cannot reach GitHub it now says so, and why, instead of reassuring you.

**The speed test can no longer drive past the safety limits.** It was writing
setpoints straight to the chamber, bypassing the clamp every run obeys.

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

The README now shows the program: pictures of every screen, woven into a
step-by-step walkthrough of a real job. The selected serial port also used to
render as a blank bar, which made it look like nothing was chosen.

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

**Update now actually updates.** It downloads the right file for your computer,
checks it against the published checksum and installs it — the Windows
installer runs on its own and the program reopens. Before this, the button only
opened the release page. The home screen also shows which version is installed,
for a chamber PC with no internet.

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

**You can now measure what your chamber actually does.** It drives the chamber
to each extreme and records how fast it really moved, five degrees at a time,
and saves it against that chamber. The setup screen then warns you when a
recipe asks for a ramp your chamber cannot follow.

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

**Every value is editable.** A Settings screen carries the connection, the run
behaviour and the safety limits, so a reconfigured controller or an unusual
chamber no longer needs a new build. A run can be given as a total time rather
than a cycle count, and cooling and heating ramps are set separately. A port
held by another program now says so, and on Linux names the program holding
it.

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

The first working version: a Watlow F4 driver that reads and commands negative
temperatures correctly.

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
