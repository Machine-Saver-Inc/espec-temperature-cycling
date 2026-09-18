"""The update path: detect, download, verify, install.

An updater that installs an unverified binary is worse than no updater, so the
checksum gate is tested from both sides.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.error

import pytest

from espec_burnin.update.checker import (
    Release,
    _parse_version,
    asset_for_this_platform,
    is_newer,
    verify_against_checksums,
)
from espec_burnin.update.installer import (
    Applied,
    UpdateError,
    apply_update,
    download_asset,
    verify_download,
)

PAYLOAD = b"pretend this is an installer" * 500


def make_release(version="0.9.0", assets=None) -> Release:
    assets = assets or {
        "EspecBurnIn-Setup-0.9.0.exe": "https://example.invalid/setup.exe",
        "espec-burn-in_0.9.0_amd64.deb": "https://example.invalid/pkg.deb",
        "EspecBurnIn-0.9.0-x86_64.AppImage": "https://example.invalid/app.AppImage",
        "SHA256SUMS": "https://example.invalid/SHA256SUMS",
    }
    return Release(
        version=version, tag=f"v{version}", notes="notes",
        html_url="https://example.invalid/release",
        assets=assets, checksums_url=assets.get("SHA256SUMS"),
    )


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def opener_for(mapping):
    def _open(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        for fragment, payload in mapping.items():
            if fragment in url:
                return FakeResponse(payload)
        raise OSError(f"unexpected url {url}")
    return _open


# --- version comparison -----------------------------------------------------

@pytest.mark.parametrize("installed,published,expected", [
    ("0.1.0", "0.3.0", True),
    ("0.3.0", "0.3.0", False),
    ("0.3.0", "0.2.0", False),
    ("1.9.0", "1.10.0", True),       # the classic string-compare trap
    ("1.10.0", "1.9.0", False),
    ("0.9.9", "1.0.0", True),
])
def test_only_a_genuinely_newer_release_is_offered(installed, published, expected):
    assert is_newer(make_release(published), installed) is expected


def test_a_tag_with_a_v_prefix_still_compares():
    assert _parse_version("v1.2.3") == (1, 2, 3)
    assert _parse_version("1.2.3-rc1") == (1, 2, 3)


# --- picking the right file -------------------------------------------------

def test_the_right_file_is_chosen_for_this_platform(monkeypatch):
    release = make_release()
    monkeypatch.setattr(sys, "platform", "win32")
    assert asset_for_this_platform(release)[0].endswith(".exe")
    monkeypatch.setattr(sys, "platform", "linux")
    # AppImage first: it can be swapped without root.
    assert asset_for_this_platform(release)[0].endswith(".AppImage")


def test_a_release_with_nothing_for_this_platform_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    release = make_release(assets={"SOURCE.tar.gz": "https://example.invalid/src"})
    with pytest.raises(UpdateError, match="no download for this type of computer"):
        download_asset(release, tmp_path)


# --- download and verification ---------------------------------------------

def test_a_download_matching_the_published_checksum_is_accepted(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    release = make_release()
    digest = hashlib.sha256(PAYLOAD).hexdigest()
    sums = f"{digest}  EspecBurnIn-Setup-0.9.0.exe\n"

    opener = opener_for({"setup.exe": PAYLOAD, "SHA256SUMS": sums.encode()})
    path = download_asset(release, tmp_path, opener=opener)
    assert path.read_bytes() == PAYLOAD
    verify_download(path, release, opener=opener)        # must not raise


def test_a_tampered_download_is_refused(monkeypatch, tmp_path):
    """The whole point of shipping SHA256SUMS."""
    monkeypatch.setattr(sys, "platform", "win32")
    release = make_release()
    sums = f"{hashlib.sha256(b'the real installer').hexdigest()}  EspecBurnIn-Setup-0.9.0.exe\n"

    opener = opener_for({"setup.exe": PAYLOAD, "SHA256SUMS": sums.encode()})
    path = download_asset(release, tmp_path, opener=opener)
    with pytest.raises(UpdateError, match="does not match the checksum"):
        verify_download(path, release, opener=opener)


def test_a_missing_checksum_list_blocks_the_install(monkeypatch, tmp_path):
    """Unverifiable is treated as untrusted, not as fine."""
    monkeypatch.setattr(sys, "platform", "win32")
    release = make_release()
    opener = opener_for({"setup.exe": PAYLOAD})   # SHA256SUMS fetch will fail
    path = download_asset(release, tmp_path, opener=opener)
    with pytest.raises(UpdateError, match="not verified"):
        verify_download(path, release, opener=opener)


def test_checksums_file_with_a_binary_star_marker_is_understood(tmp_path):
    blob = tmp_path / "thing.exe"
    blob.write_bytes(PAYLOAD)
    sums = f"{hashlib.sha256(PAYLOAD).hexdigest()} *thing.exe\n"
    assert verify_against_checksums(blob, sums)


def test_download_reports_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    seen = []
    download_asset(make_release(), tmp_path,
                   progress=lambda done, total: seen.append((done, total)),
                   opener=opener_for({"setup.exe": PAYLOAD}))
    assert seen and seen[-1][0] == len(PAYLOAD)


# --- applying ---------------------------------------------------------------

def test_windows_runs_the_installer_silently(monkeypatch, tmp_path):
    exe = tmp_path / "EspecBurnIn-Setup-0.9.0.exe"
    exe.write_bytes(PAYLOAD)
    called = {}

    def fake_launcher(args, **kwargs):
        called["args"] = args
        return None

    result = apply_update(exe, launcher=fake_launcher)
    assert result.outcome is Applied.INSTALLER_RUNNING
    assert "/SILENT" in called["args"]
    assert "/CLOSEAPPLICATIONS" in called["args"]


def test_appimage_is_replaced_in_place(monkeypatch, tmp_path):
    current = tmp_path / "EspecBurnIn.AppImage"
    current.write_bytes(b"the old version")
    monkeypatch.setenv("APPIMAGE", str(current))

    new = tmp_path / "dl" / "EspecBurnIn-0.9.0-x86_64.AppImage"
    new.parent.mkdir()
    new.write_bytes(PAYLOAD)

    result = apply_update(new)
    assert result.outcome is Applied.RESTARTING
    assert current.read_bytes() == PAYLOAD          # swapped

    # Windows has no execute bit: os.stat() only reports one for names ending
    # .exe/.bat/.cmd/.com, and chmod there toggles read-only and nothing else.
    # The swap is what matters on every platform; the mode check is POSIX only.
    if sys.platform != "win32":
        assert current.stat().st_mode & 0o111


def test_a_deb_tells_the_user_the_command_rather_than_seeking_root(tmp_path):
    deb = tmp_path / "espec-burn-in_0.9.0_amd64.deb"
    deb.write_bytes(PAYLOAD)
    result = apply_update(deb)
    assert result.outcome is Applied.MANUAL
    assert "sudo apt install" in result.message


def test_an_appimage_download_outside_an_appimage_is_not_forced(monkeypatch, tmp_path):
    monkeypatch.delenv("APPIMAGE", raising=False)
    blob = tmp_path / "EspecBurnIn-0.9.0-x86_64.AppImage"
    blob.write_bytes(PAYLOAD)
    result = apply_update(blob)
    assert result.outcome is Applied.MANUAL


# --- issue #2: a failed check reported "up to date" -------------------------
# Running 0.4.0 with 0.5.0 published, "Check for updates" said the installed
# version was newest. fetch returned None both when nothing was newer and when
# the request failed, and the window turned that None into a reassurance.

from espec_burnin.update.checker import (  # noqa: E402
    CheckOutcome,
    check_for_update_detailed,
    describe_failure,
    fetch_latest_release_detailed,
    outcome_kind,
)

FEED = {
    "tag_name": "v0.5.0",
    "body": "notes",
    "html_url": "https://example.invalid/r",
    "assets": [
        {"name": "EspecBurnIn-Setup-0.5.0.exe", "browser_download_url": "u"},
        {"name": "SHA256SUMS", "browser_download_url": "s"},
    ],
}


def feed_opener(payload=FEED):
    def _open(request, timeout=None):
        return FakeResponse(json.dumps(payload).encode())
    return _open


def failing_opener(exc):
    def _open(request, timeout=None):
        raise exc
    return _open


def test_a_reachable_feed_with_a_newer_release_offers_it(monkeypatch):
    monkeypatch.setattr(
        "espec_burnin.update.checker.fetch_latest_release_detailed",
        lambda *a, **k: fetch_latest_release_detailed(opener=feed_opener()),
    )
    outcome = check_for_update_detailed("0.4.0")
    assert outcome.reached_github
    assert outcome.update_available
    assert outcome_kind(outcome) == "update"
    assert outcome.release.version == "0.5.0"


def test_a_failed_check_is_never_reported_as_up_to_date(monkeypatch):
    """The regression. 'I could not ask' must not render as 'you are current'."""
    monkeypatch.setattr(
        "espec_burnin.update.checker.fetch_latest_release_detailed",
        lambda *a, **k: fetch_latest_release_detailed(
            opener=failing_opener(urllib.error.URLError("no route to host"))
        ),
    )
    outcome = check_for_update_detailed("0.4.0")
    assert not outcome.reached_github
    assert not outcome.update_available
    assert outcome_kind(outcome) == "unknown"      # not "current"
    assert outcome.error


def test_being_genuinely_current_is_distinguishable(monkeypatch):
    monkeypatch.setattr(
        "espec_burnin.update.checker.fetch_latest_release_detailed",
        lambda *a, **k: fetch_latest_release_detailed(opener=feed_opener()),
    )
    outcome = check_for_update_detailed("0.5.0")
    assert outcome.reached_github
    assert outcome_kind(outcome) == "current"


def test_the_three_outcomes_are_mutually_exclusive():
    assert outcome_kind(CheckOutcome(error="boom")) == "unknown"
    assert outcome_kind(CheckOutcome()) == "current"


def test_a_failure_is_retried_before_giving_up():
    calls = []

    def flaky(request, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.URLError("first attempt dropped")
        return FakeResponse(json.dumps(FEED).encode())

    release, error = fetch_latest_release_detailed(opener=flaky)
    assert error is None
    assert release.version == "0.5.0"
    assert len(calls) == 2, "a single dropped connection must not fail the check"


@pytest.mark.parametrize("exc,expected", [
    (urllib.error.URLError("[Errno -2] Name or service not known"), "no internet"),
    (TimeoutError("timed out"), "did not answer in time"),
    (urllib.error.URLError("certificate verify failed"), "could not be verified"),
])
def test_the_reason_is_explained_in_useful_words(exc, expected):
    assert expected in describe_failure(exc)


def test_the_explanation_always_includes_the_underlying_error():
    """Whoever reads the dialog has to be able to report what it said."""
    text = describe_failure(urllib.error.URLError("something unusual"))
    assert "something unusual" in text
