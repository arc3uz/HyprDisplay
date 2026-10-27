"""Pruebas de rutas, escritura atómica y edición de hyprland.lua."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hyprdisplay import config


class ConfigPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_paths(self) -> None:
        self.assertEqual(config.config_home(), self.root)
        self.assertEqual(config.app_dir(), self.root / "hyprdisplay")
        self.assertEqual(config.profiles_path(), self.root / "hyprdisplay" / "profiles.json")
        self.assertEqual(config.hypr_lua_path(), self.root / "hypr" / "hyprland.lua")
        self.assertEqual(
            config.generated_lua_path(),
            self.root / "hypr" / "config" / "monitor-profiles.lua",
        )

    def test_atomic_write_creates_parents(self) -> None:
        path = self.root / "a" / "b" / "file.txt"
        config.atomic_write(path, "hola\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "hola\n")

    def test_read_text_default(self) -> None:
        self.assertEqual(config.read_text(self.root / "no-existe", "defecto"), "defecto")


class RequireLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)})
        self.env.start()
        config.hypr_config_dir().mkdir(parents=True, exist_ok=True)
        self.lua_path = config.hypr_lua_path()
        self.lua_path.write_text(
            "require(\"config.monitors\")\n\nhl.monitor({ output = \"eDP-1\" })\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_add_require_after_monitors(self) -> None:
        changed, backup = config.add_require_line()
        self.assertTrue(changed)
        self.assertIsNotNone(backup)
        assert backup is not None
        self.assertTrue(backup.exists())

        lines = self.lua_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], 'require("config.monitors")')
        self.assertEqual(lines[1], config.REQUIRE_LINE)
        self.assertTrue(config.has_require_line())

    def test_add_require_idempotent(self) -> None:
        config.add_require_line()
        changed, backup = config.add_require_line()
        self.assertFalse(changed)
        self.assertIsNone(backup)
        text = self.lua_path.read_text(encoding="utf-8")
        self.assertEqual(text.count(config.REQUIRE_LINE), 1)

    def test_add_require_without_anchor_appends(self) -> None:
        self.lua_path.write_text("hl.env(\"XCURSOR_SIZE\", \"24\")\n", encoding="utf-8")
        changed, _ = config.add_require_line()
        self.assertTrue(changed)
        lines = self.lua_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[-1], config.REQUIRE_LINE)

    def test_missing_hyprland_lua(self) -> None:
        self.lua_path.unlink()
        with self.assertRaises(config.ConfigError):
            config.add_require_line()


class ShortcutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)})
        self.env.start()
        config.hypr_config_dir().mkdir(parents=True, exist_ok=True)
        self.path = config.binds_path()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_replace_existing_bind(self) -> None:
        self.path.write_text(
            'hl.bind(mainMod .. " + P",\n'
            '    hl.dsp.exec_cmd("~/.config/hypr/scripts/monitor_selector.sh"))\n',
            encoding="utf-8",
        )
        status, backup = config.install_shortcut()
        self.assertEqual(status, "replaced")
        self.assertIsNotNone(backup)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("hyprdisplay gui", text)
        self.assertNotIn("monitor_selector.sh", text)
        self.assertEqual(text.count("hl.bind("), 1)

    def test_replace_cycle_bind_with_gui(self) -> None:
        self.path.write_text(
            'hl.bind("SUPER + P", hl.dsp.exec_cmd("hyprdisplay cycle"))\n',
            encoding="utf-8",
        )
        status, _ = config.install_shortcut()
        self.assertEqual(status, "replaced")
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("hyprdisplay gui", text)
        self.assertNotIn("hyprdisplay cycle", text)

    def test_add_bind_when_missing(self) -> None:
        self.path.write_text('hl.bind("SUPER + Q", hl.dsp.window.close())\n', encoding="utf-8")
        status, backup = config.install_shortcut()
        self.assertEqual(status, "added")
        self.assertIsNotNone(backup)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("hl.bind(\"SUPER + P\"", text)
        self.assertIn("hyprdisplay gui", text)

    def test_present_bind(self) -> None:
        self.path.write_text(
            'hl.bind("SUPER + P", hl.dsp.exec_cmd("hyprdisplay gui"))\n',
            encoding="utf-8",
        )
        status, backup = config.install_shortcut()
        self.assertEqual(status, "present")
        self.assertIsNone(backup)

    def test_custom_key(self) -> None:
        self.path.write_text('hl.bind("SUPER + P", hl.dsp.window.close())\n', encoding="utf-8")
        status, _ = config.install_shortcut("SUPER + ALT + P")
        self.assertEqual(status, "added")
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('hl.bind("SUPER + ALT + P"', text)
        self.assertIn('hl.bind("SUPER + P"', text)

    def test_missing_binds_file(self) -> None:
        with self.assertRaises(config.ConfigError):
            config.install_shortcut()


if __name__ == "__main__":
    unittest.main()
