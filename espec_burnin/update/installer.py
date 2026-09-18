"""Downloading and applying an update.

Kept free of Qt so the download, the checksum check and the decision about how
to install can be tested without a running application.

Nothing here runs while a burn-in is in progress; the caller enforces that.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from espec_burnin import __version__
from espec_burnin.update.checker import (
    Release,
    asset_for_this_platform,
    sha256,
    verify_against_checksums,
)

log = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_S = 60
CHUNK = 256 * 1024


class UpdateError(Exception):
    """Something went wrong that the user needs to be told about."""


class Applied(str, Enum):
    RESTARTING = "restarting"      # the program is about to close and come back
    INSTALLER_RUNNING = "installer_running"
    MANUAL = "manual"              # the file is downloaded; the user finishes


@dataclass
class ApplyResult:
    outcome: Applied
    message: str
    path: Path


def running_appimage() -> Path | None:
    """The AppImage we were launched from, if that is how we are running."""
    value = os.environ.get("APPIMAGE")
    return Path(value) if value else None


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def download_asset(
    release: Release,
    destination: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    opener: Callable = urllib.request.urlopen,
) -> Path:
    """Fetch the file for this platform. Raises UpdateError with a readable reason."""
    chosen = asset_for_this_platform(release)
    if chosen is None:
        raise UpdateError(
            "This release has no download for this type of computer. "
            "Open the release page and pick a file by hand."
        )
    name, url = chosen
    folder = destination or Path(tempfile.mkdtemp(prefix="espec-update-"))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name

    request = urllib.request.Request(
        url, headers={"User-Agent": f"espec-burn-in/{__version__}"}
    )
    try:
        with opener(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with target.open("wb") as handle:
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    done += len(block)
                    if progress:
                        progress(done, total)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"The download did not finish: {exc}") from exc
    return target


def fetch_checksums(release: Release, opener: Callable = urllib.request.urlopen) -> str:
    if not release.checksums_url:
        return ""
    request = urllib.request.Request(
        release.checksums_url, headers={"User-Agent": f"espec-burn-in/{__version__}"}
    )
    try:
        with opener(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
            return response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("could not fetch SHA256SUMS: %s", exc)
        return ""


def verify_download(path: Path, release: Release, opener=urllib.request.urlopen) -> None:
    """Refuse to run anything whose hash is not the one the release published."""
    text = fetch_checksums(release, opener)
    if not text:
        raise UpdateError(
            "Could not fetch the checksum list for this release, so the download "
            "was not verified and will not be installed. Try again later, or "
            "install it by hand from the release page."
        )
    if not verify_against_checksums(path, text):
        raise UpdateError(
            f"The downloaded file does not match the checksum published with the "
            f"release, so it will not be installed.\n\n{path.name}\n"
            f"got {sha256(path)[:16]}…"
        )


def apply_update(path: Path, *, launcher: Callable = subprocess.Popen) -> ApplyResult:
    """Install the verified download, as far as this platform allows."""
    name = path.name.lower()

    if name.endswith(".exe"):
        try:
            # Inno Setup: install without prompting, close this program first,
            # and start it again afterwards.
            launcher([
                str(path), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS",
                "/NOCANCEL",
            ])
        except OSError as exc:
            raise UpdateError(f"The installer would not start: {exc}") from exc
        return ApplyResult(
            Applied.INSTALLER_RUNNING,
            "The installer is running. This program will close and reopen on the "
            "new version.",
            path,
        )

    if name.endswith(".appimage"):
        current = running_appimage()
        if current is None:
            return ApplyResult(
                Applied.MANUAL,
                f"Downloaded to {path}. Replace your current AppImage with it, "
                f"then make it executable with chmod +x.",
                path,
            )
        try:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            staged = current.with_suffix(current.suffix + ".new")
            shutil.copy2(path, staged)
            os.replace(staged, current)   # atomic on the same filesystem
        except OSError as exc:
            raise UpdateError(
                f"Could not replace {current}: {exc}. You may not have permission "
                f"to write there."
            ) from exc
        return ApplyResult(
            Applied.RESTARTING,
            "Updated. This program will restart on the new version.",
            current,
        )

    if name.endswith(".deb"):
        return ApplyResult(
            Applied.MANUAL,
            "Downloaded. Install it with:\n\n"
            f"    sudo apt install {path}\n\n"
            "This program cannot install system packages on your behalf.",
            path,
        )

    return ApplyResult(Applied.MANUAL, f"Downloaded to {path}.", path)


def relaunch(target: Path | None = None) -> None:
    """Start the new version and let this process exit."""
    executable = target or running_appimage()
    if executable is None:
        executable = Path(sys.executable)
    try:
        subprocess.Popen([str(executable)], close_fds=True)
    except OSError as exc:  # noqa: BLE001 - the user can reopen it themselves
        log.warning("could not relaunch: %s", exc)
