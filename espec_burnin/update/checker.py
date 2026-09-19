"""Update checking against GitHub Releases.

The repository is public, so this needs no token and no server of our own.
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from espec_burnin import GITHUB_REPO, __version__
from espec_burnin.update.net import open_url

log = logging.getLogger(__name__)

LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
TIMEOUT_S = 15.0          # a corporate proxy is slower than a laptop on wifi
ATTEMPTS = 2


@dataclass(frozen=True)
class CheckOutcome:
    """What a check actually established.

    A failed request and "you are on the newest release" are completely
    different facts, and telling a user the reassuring one when the truthful one
    is "I could not reach GitHub" is how a broken updater goes unnoticed.
    """

    release: Release | None = None     # set only when something NEWER exists
    latest: Release | None = None      # whatever the feed returned, if reached
    error: str | None = None

    @property
    def reached_github(self) -> bool:
        return self.error is None

    @property
    def update_available(self) -> bool:
        return self.release is not None


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    notes: str
    html_url: str
    assets: dict[str, str]        # filename -> download url
    checksums_url: str | None


def _parse_version(text: str) -> tuple:
    """Compare versions numerically so 1.10.0 beats 1.9.0."""
    cleaned = text.lstrip("vV").split("+")[0].split("-")[0]
    parts = []
    for chunk in cleaned.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def asset_pattern_for_this_platform() -> tuple[str, ...]:
    if sys.platform == "win32":
        return (".exe",)
    if sys.platform.startswith("linux"):
        # AppImage first: it can be swapped in place without root.
        return (".AppImage", ".deb")
    return ()


# Kept as a name here because callers and tests already reach for it; the
# implementation lives in one place so the downloader gets the same handling.
_open = open_url


def fetch_latest_release_detailed(
    url: str = LATEST_RELEASE_URL, opener=None
) -> tuple[Release | None, str | None]:
    """Ask GitHub for the newest release.

    Returns ``(release, None)`` on success or ``(None, reason)`` on failure.
    Never raises: startup must not wait on the network.
    """
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"espec-burn-in/{__version__}",
        },
    )
    open_it = opener or _open

    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            with open_it(request, timeout=TIMEOUT_S) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last = exc
            log.info("update check attempt %d failed: %s", attempt + 1, exc)
    else:
        return None, describe_failure(last)

    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    return Release(
        version=str(data.get("tag_name", "")).lstrip("vV"),
        tag=data.get("tag_name", ""),
        notes=data.get("body") or "",
        html_url=data.get("html_url", RELEASES_PAGE),
        assets=assets,
        checksums_url=assets.get("SHA256SUMS"),
    ), None


def describe_failure(exc: Exception | None) -> str:
    """Say what went wrong in words the person at the chamber can act on."""
    if exc is None:
        return "The update check did not complete."
    text = str(exc)
    lowered = text.lower()
    if "certificate" in lowered or "ssl" in lowered:
        return ("The secure connection to GitHub could not be verified. This is "
                "usually a company proxy or an out-of-date certificate store.\n\n"
                f"{text}")
    if "timed out" in lowered or isinstance(exc, TimeoutError):
        return ("GitHub did not answer in time. The network may be slow or "
                f"blocked.\n\n{text}")
    if "name or service not known" in lowered or "getaddrinfo" in lowered \
            or "nodename nor servname" in lowered:
        return ("github.com could not be looked up. This computer may have no "
                f"internet connection.\n\n{text}")
    if "forbidden" in lowered or "403" in text:
        return ("GitHub refused the request. If several programs share this "
                f"connection, the hourly limit may have been reached.\n\n{text}")
    return f"Could not reach GitHub.\n\n{text}"


def fetch_latest_release(url: str = LATEST_RELEASE_URL) -> Release | None:
    """Backwards-compatible wrapper. Prefer fetch_latest_release_detailed."""
    release, _error = fetch_latest_release_detailed(url)
    return release


def is_newer(release: Release, current: str = __version__) -> bool:
    return _parse_version(release.version) > _parse_version(current)


def check_for_update(current: str = __version__) -> Release | None:
    """Backwards-compatible wrapper. Prefer check_for_update_detailed."""
    return check_for_update_detailed(current).release


def outcome_kind(outcome: CheckOutcome) -> str:
    """What the UI should say: 'update', 'current' or 'unknown'.

    Kept out of the window so it can be tested directly. Conflating 'unknown'
    with 'current' is what made a broken update check look like a working one.
    """
    if outcome.update_available:
        return "update"
    if outcome.reached_github:
        return "current"
    return "unknown"


def check_for_update_detailed(current: str = __version__) -> CheckOutcome:
    """Check, and report what was actually established."""
    latest, error = fetch_latest_release_detailed()
    if error is not None:
        return CheckOutcome(error=error)
    if latest is not None and is_newer(latest, current):
        return CheckOutcome(release=latest, latest=latest)
    return CheckOutcome(latest=latest)


def asset_for_this_platform(release: Release) -> tuple[str, str] | None:
    for suffix in asset_pattern_for_this_platform():
        for name, url in release.assets.items():
            if name.endswith(suffix):
                return name, url
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_against_checksums(path: Path, checksums_text: str) -> bool:
    """Refuse to run anything whose hash is not in the release's SHA256SUMS."""
    expected = {
        parts[1].lstrip("*"): parts[0]
        for line in checksums_text.splitlines()
        if len(parts := line.split()) == 2
    }
    wanted = expected.get(path.name)
    return bool(wanted) and wanted.lower() == sha256(path).lower()


def platform_install_hint(asset_name: str) -> str:
    """What the program tells the user it is about to do."""
    if asset_name.endswith(".exe"):
        return "The installer will run and this program will close and reopen."
    if asset_name.endswith(".AppImage"):
        return "The application file will be replaced and the program will restart."
    if asset_name.endswith(".deb"):
        return (
            "Downloaded. Install it with:\n"
            f"    sudo apt install ./{asset_name}\n"
            "This program cannot install system packages on your behalf."
        )
    return f"Downloaded to your Downloads folder. Platform: {platform.system()}."
