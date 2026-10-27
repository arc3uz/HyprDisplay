"""Pruebas de la lógica compartida de aplicación (sin tocar Hyprland real)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hyprdisplay import config, core, hypr, profiles
from hyprdisplay.hypr import Mode
from hyprdisplay.layout import MonitorState


def make_monitor(name: str = "eDP-1", **kwargs) -> MonitorState:
    defaults = dict(
        description=f"Monitor {name}",
        serial=f"serial-{name}",
        available_modes=[Mode(1920, 1080, 60.0)],
        width=1920,
        height=1080,
        refresh=60.0,
        scale=1.0,
    )
    defaults.update(kwargs)
    return MonitorState(name=name, **defaults)


class ApplyPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name})
        self.env.start()
        config.ensure_hypr_config_dir()

        self.monitors = [make_monitor("eDP-1"), make_monitor("HDMI-A-1", x=1920)]
        self.store = profiles.ProfileStore()
        self.profile = profiles.Profile.from_monitors(
            "Escritorio", self.monitors, primary="eDP-1"
        )
        self.store.upsert(self.profile)
        self.store.save()
        self.state = profiles.State(primary="eDP-1")
        self.path = config.profiles_path()
        self.original = self.path.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_quick_mode_does_not_rewrite_profiles(self) -> None:
        with (
            mock.patch.object(hypr, "eval_lua", return_value="ok"),
            mock.patch.object(hypr, "get_config_errors", return_value=""),
        ):
            result = core.apply_quick_mode(
                "extend", self.monitors, self.store, self.state
            )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.original)

    def test_failed_apply_keeps_profiles(self) -> None:
        with mock.patch.object(
            hypr, "eval_lua", side_effect=hypr.HyprError("fallo simulado")
        ):
            result = core.apply_profile(
                self.profile, self.monitors, self.store, self.state
            )
        self.assertFalse(result.ok)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.original)

    def test_successful_profile_apply_updates_last_used(self) -> None:
        self.profile.last_used = 1
        self.store.save()
        with (
            mock.patch.object(hypr, "eval_lua", return_value="ok"),
            mock.patch.object(hypr, "get_config_errors", return_value=""),
        ):
            result = core.apply_profile(
                self.profile, self.monitors, self.store, self.state
            )
        self.assertTrue(result.ok, result.errors)
        reloaded = profiles.ProfileStore(self.path)
        self.assertGreater(reloaded.profiles[0].last_used, 1)
        self.assertEqual(reloaded.names(), ["Escritorio"])

    def test_apply_writes_generated_lua(self) -> None:
        with (
            mock.patch.object(hypr, "eval_lua", return_value="ok"),
            mock.patch.object(hypr, "get_config_errors", return_value=""),
        ):
            core.apply_quick_mode("extend", self.monitors, self.store, self.state)
        text = config.generated_lua_path().read_text(encoding="utf-8")
        self.assertIn('output = "eDP-1"', text)
        self.assertIn('name = "Escritorio"', text)

    def test_apply_pre_enables_disabled_output_before_mirroring(self) -> None:
        live = [
            SimpleNamespace(name="eDP-1", disabled=False),
            SimpleNamespace(name="HDMI-A-1", disabled=True),
        ]
        rules = [
            {
                "output": "eDP-1",
                "mode": "1920x1080@60",
                "position": "0x0",
                "scale": 1.0,
                "transform": 0,
                "mirror": "",
                "disabled": False,
            },
            {
                "output": "HDMI-A-1",
                "mode": "1920x1080@60",
                "position": "0x0",
                "scale": 1.0,
                "transform": 0,
                "mirror": "eDP-1",
                "disabled": False,
            },
        ]
        calls: list[str] = []

        def fake_eval(code: str) -> str:
            calls.append(code)
            return "ok"

        with (
            mock.patch.object(hypr, "get_monitors", return_value=live),
            mock.patch.object(hypr, "eval_lua", side_effect=fake_eval),
            mock.patch.object(hypr, "get_config_errors", return_value=""),
            mock.patch.object(core.time, "sleep", return_value=None),
        ):
            result = core.apply_rules(rules, self.store, self.state)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(len(calls), 2)
        # Primero se enciende HDMI sin espejo; después la regla definitiva.
        self.assertIn('mirror = ""', calls[0])
        self.assertIn('mirror = "eDP-1"', calls[1])


class PreEnableTests(unittest.TestCase):
    def test_disabled_to_mirrored_needs_pre_enable(self) -> None:
        new = [{"output": "HDMI-A-1", "disabled": False, "mirror": "eDP-1"}]
        pre = core.pre_enable_rules({"HDMI-A-1"}, new)
        self.assertEqual(len(pre), 1)
        self.assertEqual(pre[0]["mirror"], "")
        self.assertFalse(pre[0]["disabled"])

    def test_disabled_monitor_unknown_to_state_needs_pre_enable(self) -> None:
        # Hyprland dice que está desactivado aunque el estado guardado dijera
        # lo contrario; manda el estado real.
        new = [{"output": "HDMI-A-1", "disabled": False, "mirror": "eDP-1"}]
        self.assertEqual(len(core.pre_enable_rules({"HDMI-A-1"}, new)), 1)

    def test_already_enabled_mirror_needs_no_pre_enable(self) -> None:
        new = [{"output": "HDMI-A-1", "disabled": False, "mirror": "eDP-1"}]
        self.assertEqual(core.pre_enable_rules(set(), new), [])

    def test_unmirrored_rule_needs_no_pre_enable(self) -> None:
        new = [{"output": "HDMI-A-1", "disabled": False, "mirror": ""}]
        self.assertEqual(core.pre_enable_rules({"HDMI-A-1"}, new), [])

    def test_disabled_target_ignored(self) -> None:
        new = [{"output": "HDMI-A-1", "disabled": True, "mirror": "eDP-1"}]
        self.assertEqual(core.pre_enable_rules({"HDMI-A-1"}, new), [])

    def test_only_disabled_outputs_get_pre_enable(self) -> None:
        new = [
            {"output": "eDP-1", "disabled": False, "mirror": "HDMI-A-1"},
            {"output": "HDMI-A-1", "disabled": False, "mirror": "eDP-1"},
        ]
        pre = core.pre_enable_rules({"HDMI-A-1"}, new)
        self.assertEqual([rule["output"] for rule in pre], ["HDMI-A-1"])


class OutputRepairTests(unittest.TestCase):
    def test_invisible_output_detected(self) -> None:
        monitors = [make_monitor("eDP-1"), make_monitor("HDMI-A-1", x=1920)]
        with mock.patch.object(hypr, "wayland_outputs", return_value={"eDP-1"}):
            self.assertEqual(core.invisible_outputs(monitors), ["HDMI-A-1"])

    def test_mirrored_monitor_is_expected_invisible(self) -> None:
        monitors = [make_monitor("eDP-1"), make_monitor("HDMI-A-1", mirror="eDP-1")]
        with mock.patch.object(hypr, "wayland_outputs", return_value={"eDP-1"}):
            self.assertEqual(core.invisible_outputs(monitors), [])

    def test_disabled_monitor_is_ignored(self) -> None:
        monitors = [make_monitor("eDP-1"), make_monitor("HDMI-A-1", disabled=True)]
        with mock.patch.object(hypr, "wayland_outputs", return_value={"eDP-1"}):
            self.assertEqual(core.invisible_outputs(monitors), [])

    def test_without_wayland_info_returns_empty(self) -> None:
        with mock.patch.object(hypr, "wayland_outputs", return_value=None):
            self.assertEqual(core.invisible_outputs([make_monitor("eDP-1")]), [])

    def test_repair_toggles_output(self) -> None:
        monitors = [make_monitor("HDMI-A-1")]
        calls: list[str] = []

        def fake_eval(code: str) -> str:
            calls.append(code)
            return "ok"

        with (
            mock.patch.object(hypr, "wayland_outputs", return_value=set()),
            mock.patch.object(hypr, "eval_lua", side_effect=fake_eval),
            mock.patch.object(core.time, "sleep", return_value=None),
        ):
            repaired = core.repair_outputs(monitors)

        self.assertEqual(repaired, ["HDMI-A-1"])
        self.assertEqual(len(calls), 2)
        self.assertIn("disabled = true", calls[0])
        self.assertIn("disabled = false", calls[1])


if __name__ == "__main__":
    unittest.main()
