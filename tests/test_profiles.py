"""Pruebas de perfiles, coincidencia por EDID y estado persistente."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hyprdisplay import profiles
from hyprdisplay.hypr import Mode
from hyprdisplay.layout import MonitorState


def make_monitor(name: str, serial: str | None = None, **kwargs) -> MonitorState:
    defaults = dict(
        description=f"Monitor {name}",
        serial=serial if serial is not None else f"serial-{name}",
        available_modes=[Mode(1920, 1080, 60.0)],
        width=1920,
        height=1080,
        refresh=60.0,
        scale=1.0,
    )
    defaults.update(kwargs)
    return MonitorState(name=name, **defaults)


class ProfileMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.monitors = [
            make_monitor("eDP-1", x=0),
            make_monitor("HDMI-A-1", x=1280),
        ]
        self.profile = profiles.Profile.from_monitors(
            "Escritorio", self.monitors, primary="eDP-1"
        )

    def test_match_score_exact(self) -> None:
        self.assertEqual(self.profile.match_score(self.monitors), 4)

    def test_match_score_swapped_ports(self) -> None:
        swapped = [
            make_monitor("HDMI-A-1", description="Monitor eDP-1", serial="serial-eDP-1", x=0),
            make_monitor("eDP-1", description="Monitor HDMI-A-1", serial="serial-HDMI-A-1", x=1280),
        ]
        score = self.profile.match_score(swapped)
        self.assertIsNotNone(score)
        assert score is not None
        self.assertEqual(score, 2)

    def test_no_match_with_extra_monitor(self) -> None:
        extra = self.monitors + [make_monitor("DP-1", x=3000)]
        self.assertIsNone(self.profile.match_score(extra))

    def test_match_with_changed_serial_by_port(self) -> None:
        other = [make_monitor("eDP-1", serial="otro"), make_monitor("HDMI-A-1")]
        score = self.profile.match_score(other)
        self.assertIsNotNone(score)

    def test_no_match_with_different_description_and_serial(self) -> None:
        other = [
            make_monitor("eDP-1", description="Otro", serial="otro"),
            make_monitor("HDMI-A-1"),
        ]
        self.assertIsNone(self.profile.match_score(other))

    def test_matches_layout(self) -> None:
        self.assertTrue(self.profile.matches_layout(self.monitors))

    def test_does_not_match_layout_after_change(self) -> None:
        changed = [self.monitors[0], make_monitor("HDMI-A-1", x=1920)]
        self.assertFalse(self.profile.matches_layout(changed))

    def test_auto_flag(self) -> None:
        self.assertTrue(self.profile.auto)
        self.profile.auto = False
        self.assertFalse(self.profile.auto)


class ProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "profiles.json"
        self.store = profiles.ProfileStore(self.path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_save_and_reload(self) -> None:
        monitor = make_monitor("eDP-1")
        profile = profiles.Profile.from_monitors("Solo", [monitor], primary="eDP-1")
        self.store.upsert(profile)
        self.store.save()

        reloaded = profiles.ProfileStore(self.path)
        self.assertEqual(reloaded.names(), ["Solo"])
        self.assertEqual(reloaded.profiles[0].primary, "eDP-1")
        self.assertEqual(len(reloaded.profiles[0].monitors), 1)
        self.assertEqual(reloaded.profiles[0].monitors[0].fingerprint, monitor.fingerprint)

    def test_upsert_replaces_same_name(self) -> None:
        first = profiles.Profile.from_monitors("Perfil", [make_monitor("eDP-1")])
        second = profiles.Profile.from_monitors("Perfil", [make_monitor("HDMI-A-1")])
        self.store.upsert(first)
        self.store.upsert(second)
        self.assertEqual(len(self.store.profiles), 1)
        self.assertEqual(self.store.profiles[0].monitors[0].port, "HDMI-A-1")

    def test_delete(self) -> None:
        profile = profiles.Profile.from_monitors("Perfil", [make_monitor("eDP-1")])
        self.store.upsert(profile)
        self.assertTrue(self.store.delete("Perfil"))
        self.assertFalse(self.store.delete("Perfil"))
        self.assertEqual(self.store.profiles, [])

    def test_match_prefers_port_tiebreak(self) -> None:
        monitors = [
            make_monitor("eDP-1", description="A", serial="1"),
            make_monitor("HDMI-A-1", description="B", serial="2"),
        ]
        exact = profiles.Profile.from_monitors(
            "Exacto",
            [
                make_monitor("eDP-1", description="A", serial="1"),
                make_monitor("HDMI-A-1", description="B", serial="2"),
            ],
        )
        swapped = profiles.Profile.from_monitors(
            "Cruzado",
            [
                make_monitor("HDMI-A-1", description="A", serial="1"),
                make_monitor("eDP-1", description="B", serial="2"),
            ],
        )
        exact.last_used = 1
        swapped.last_used = 2
        self.store.upsert(swapped)
        self.store.upsert(exact)
        matched = self.store.match(monitors)
        self.assertIsNotNone(matched)
        assert matched is not None
        self.assertEqual(matched.name, "Exacto")

    def test_match_ignores_manual_profiles(self) -> None:
        profile = profiles.Profile.from_monitors("Manual", [make_monitor("eDP-1")], auto=False)
        self.store.upsert(profile)
        self.assertIsNone(self.store.match([make_monitor("eDP-1")]))

    def test_import_export(self) -> None:
        source = profiles.Profile.from_monitors("Origen", [make_monitor("eDP-1")])
        self.store.upsert(source)
        self.store.save()

        exported = Path(self.tmp.name) / "export.json"
        self.store.export_to(exported)

        other_path = Path(self.tmp.name) / "otros.json"
        other = profiles.ProfileStore(other_path)
        count = other.import_from(exported)
        self.assertEqual(count, 1)
        self.assertEqual(other.names(), ["Origen"])

    def test_import_invalid_json(self) -> None:
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("{no es json", encoding="utf-8")
        with self.assertRaises(Exception):
            self.store.import_from(bad)

    def test_load_missing_file(self) -> None:
        self.assertEqual(self.store.profiles, [])


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_default_state(self) -> None:
        store = profiles.StateStore(self.path)
        self.assertEqual(store.state.active_profile, "")
        self.assertEqual(store.state.current_rules, [])

    def test_save_and_reload(self) -> None:
        store = profiles.StateStore(self.path)
        store.state.active_profile = "Escritorio"
        store.state.primary = "eDP-1"
        store.state.current_rules = [make_monitor("eDP-1").to_rule()]
        store.state.previous_rules = [make_monitor("HDMI-A-1").to_rule()]
        store.save()

        reloaded = profiles.StateStore(self.path)
        self.assertEqual(reloaded.state.active_profile, "Escritorio")
        self.assertEqual(reloaded.state.primary, "eDP-1")
        self.assertEqual(reloaded.state.current_rules[0]["output"], "eDP-1")
        self.assertEqual(reloaded.state.previous_rules[0]["output"], "HDMI-A-1")

    def test_save_writes_json(self) -> None:
        store = profiles.StateStore(self.path)
        store.save()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)


if __name__ == "__main__":
    unittest.main()
