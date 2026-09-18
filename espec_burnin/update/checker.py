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

log = logging.getLogger(__name__)

LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
TIMEOUT_S = 5.0


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


def fetch_latest_release(url: str = LATEST_RELEASE_URL) -> Release | None:
    """Ask GitHub for the newest release. Returns None on any failure.

    Never raises and never blocks startup: no network, DNS failure, a proxy in
    the way and GitHub being down all look the same from here, and none of them
    are worth interrupting the user over.
    """
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"espec-burn-in/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        log.info("update check skipped: %s", exc)
        return None

    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    return Release(
        version=str(data.get("tag_name", "")).lstrip("vV"),
        tag=data.get("tag_name", ""),
        notes=data.get("body") or "",
        html_url=data.get("html_url", RELEASES_PAGE),
        assets=assets,
        checksums_url=assets.get("SHA256SUMS"),
    )


def is_newer(release: Release, current: str = __version__) -> bool:
    return _parse_version(release.version) > _parse_version(current)


def check_for_update(current: str = __version__) -> Release | None:
    release = fetch_latest_release()
    if release and is_newer(release, current):
        return release
    return None


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
