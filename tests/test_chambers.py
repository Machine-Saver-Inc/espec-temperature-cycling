"""Chambers, and the tests that hang underneath them.

A measured profile belongs to a physical chamber identified the way the shop
floor identifies it -- model and serial number -- not to a free-text label.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from espec_burnin.core.capability import (
    ChamberProfile,
    best_profile_for,
    load_profiles,
    load_profiles_for,
    save_profile,
)
from espec_burnin.core.chambers import (
    Chamber,
    find,
    find_by_adapter,
    known_models,
    load_chambers,
    save_chamber,
    serials_for_model,
    slug,
)

BTZ = dict(chamber_model="Espec BTZ-133", chamber_serial="0612223")
ARS = dict(chamber_model="Espec ARS-220", chamber_serial="99104")


@pytest.fixture
def store(tmp_path):
    with mock.patch("espec_burnin.core.chambers.chambers_path",
                    return_value=tmp_path / "chambers.json"), \
         mock.patch("espec_burnin.core.capability.profiles_dir",
                    return_value=tmp_path / "profiles"):
        yield tmp_path


# --- the chamber registry ---------------------------------------------------

def test_a_chamber_is_identified_by_model_and_serial(store):
    save_chamber(Chamber(model="Espec BTZ-133", serial="0612223"))
    found = find("Espec BTZ-133", "0612223")
    assert found is not None
    assert found.label == "Espec BTZ-133 — Serial 0612223"


def test_an_unnamed_chamber_is_not_stored(store):
    save_chamber(Chamber(model="", serial=""))
    save_chamber(Chamber(model="Espec BTZ-133", serial=""))
    assert load_chambers() == []


def test_saving_the_same_chamber_twice_updates_rather_than_duplicates(store):
    save_chamber(Chamber(model="Espec BTZ-133", serial="0612223", last_port="COM3"))
    save_chamber(Chamber(model="Espec BTZ-133", serial="0612223", last_port="COM7"))
    chambers = load_chambers()
    assert len(chambers) == 1
    assert chambers[0].last_port == "COM7"


def test_the_first_seen_date_survives_an_update(store):
    save_chamber(Chamber(model="Espec BTZ-133", serial="0612223"))
    original = load_chambers()[0].first_seen
    save_chamber(Chamber(model="Espec BTZ-133", serial="0612223", last_port="COM9"))
    assert load_chambers()[0].first_seen == original


def test_a_chamber_is_recognised_from_the_adapter_it_was_reached_through(store):
    """Plugging the same adapter in should identify the chamber with no typing."""
    save_chamber(Chamber(model="Espec BTZ-133", serial="0612223",
                         adapter_serial="AB0KX1QZ"))
    save_chamber(Chamber(model="Espec ARS-220", serial="99104",
                         adapter_serial="FT9ZZZ11"))

    assert find_by_adapter("AB0KX1QZ").serial == "0612223"
    assert find_by_adapter("FT9ZZZ11").serial == "99104"
    assert find_by_adapter("unknown-adapter") is None
    assert find_by_adapter(None) is None


def test_models_and_their_serials_are_offered_for_reuse(store):
    save_chamber(Chamber(model="Espec BTZ-133", serial="0612223"))
    save_chamber(Chamber(model="Espec BTZ-133", serial="0612224"))
    save_chamber(Chamber(model="Espec ARS-220", serial="99104"))

    assert set(known_models()) == {"Espec BTZ-133", "Espec ARS-220"}
    assert set(serials_for_model("Espec BTZ-133")) == {"0612223", "0612224"}
    assert serials_for_model("Espec ARS-220") == ["99104"]


def test_a_missing_registry_is_not_an_error(store):
    assert load_chambers() == []
    assert known_models() == []


@pytest.mark.parametrize("raw,expected", [
    ("Espec BTZ-133", "Espec-BTZ-133"),
    ("  spaces  ", "spaces"),
    ("bad/chars:here", "bad-chars-here"),
    ("", "unknown"),
])
def test_names_are_made_safe_for_the_filesystem(raw, expected):
    assert slug(raw) == expected


# --- tests hang underneath their chamber ------------------------------------

def test_tests_are_scoped_to_their_chamber(store):
    save_profile(ChamberProfile(**BTZ, name="Loaded — 12 boards", loaded=True))
    save_profile(ChamberProfile(**BTZ, name="Empty, ports closed", loaded=False))
    save_profile(ChamberProfile(**ARS, name="Loaded"))

    btz = {p.name for p in load_profiles_for(**{"model": BTZ["chamber_model"],
                                                "serial": BTZ["chamber_serial"]})}
    assert btz == {"Loaded — 12 boards", "Empty, ports closed"}
    assert len(load_profiles()) == 3
    assert [p.name for p in load_profiles_for("Espec ARS-220", "99104")] == ["Loaded"]


def test_the_loaded_test_is_preferred_for_checking_a_recipe(store):
    """An empty chamber is the best case, not the case the boards will see."""
    save_profile(ChamberProfile(**BTZ, name="Empty, ports closed", loaded=False))
    save_profile(ChamberProfile(**BTZ, name="Loaded — 12 boards", loaded=True))
    assert best_profile_for("Espec BTZ-133", "0612223").name == "Loaded — 12 boards"


def test_an_abandoned_measurement_is_not_used_to_check_recipes(store):
    save_profile(ChamberProfile(**BTZ, name="Stopped early", loaded=True, aborted=True))
    assert best_profile_for("Espec BTZ-133", "0612223") is None


def test_a_chamber_with_no_tests_yields_nothing(store):
    save_profile(ChamberProfile(**BTZ, name="Loaded"))
    assert load_profiles_for("Espec ARS-220", "99104") == []
    assert best_profile_for("Espec ARS-220", "99104") is None


def test_reusing_a_test_name_replaces_that_test_not_the_chamber(store):
    save_profile(ChamberProfile(**BTZ, name="Loaded", reachable_min_c=-14.0))
    save_profile(ChamberProfile(**BTZ, name="Loaded", reachable_min_c=-19.0))
    profiles = load_profiles_for("Espec BTZ-133", "0612223")
    assert len(profiles) == 1
    assert profiles[0].reachable_min_c == -19.0


def test_profiles_saved_before_chambers_existed_are_still_read(store, tmp_path):
    """The flat layout from an earlier version must not be silently lost."""
    import json

    folder = tmp_path / "profiles"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "old.json").write_text(json.dumps({
        "name": "Loaded — legacy", "loaded": True, "cooling_rates": {"2.5": 1.0},
        "measured_at": "2026-01-01T00:00:00",
    }), encoding="utf-8")

    names = [p.name for p in load_profiles()]
    assert "Loaded — legacy" in names


def test_a_profile_knows_which_chamber_it_describes():
    profile = ChamberProfile(**BTZ, name="Loaded")
    assert profile.chamber_label == "Espec BTZ-133 — Serial 0612223"
    assert profile.chamber_key == "Espec-BTZ-133__0612223"


def test_a_run_records_which_chamber_it_ran_on(tmp_path):
    from espec_burnin.core.profile import Recipe
    from espec_burnin.core.recorder import Recorder

    with mock.patch("espec_burnin.core.recorder.results_root", return_value=tmp_path):
        recorder = Recorder(batch="MS-4412", operator="Leo", recipe=Recipe(),
                            port="COM3", chamber_model="Espec BTZ-133",
                            chamber_serial="0612223")
        state = Recorder.load_state(Path(recorder.folder))

    assert state["chamber_model"] == "Espec BTZ-133"
    assert state["chamber_serial"] == "0612223"
