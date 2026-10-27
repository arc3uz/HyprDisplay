"""Pruebas de generación de Lua y de los comandos de eval."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from hyprdisplay import lua, profiles
from hyprdisplay.hypr import Mode
from hyprdisplay.layout import MonitorState


def make_monitor(name: str, **kwargs) -> MonitorState:
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


class QuoteTests(unittest.TestCase):
    def test_quote_plain(self) -> None:
        self.assertEqual(lua.lua_quote("hola"), '"hola"')

    def test_quote_escapes(self) -> None:
        self.assertEqual(lua.lua_quote('a"b'), '"a\\"b"')
        self.assertEqual(lua.lua_quote("a\\b"), '"a\\\\b"')
        self.assertEqual(lua.lua_quote("a\nb"), '"a\\nb"')

    def test_quote_non_string(self) -> None:
        self.assertEqual(lua.lua_quote(42), '"42"')

    def test_number(self) -> None:
        self.assertEqual(lua.lua_number(1.5), "1.5")
        self.assertEqual(lua.lua_number(2.0), "2")
        self.assertEqual(lua.lua_number(True), "true")
        self.assertEqual(lua.lua_number(False), "false")


class RuleLuaTests(unittest.TestCase):
    def test_rule_to_lua_contains_all_fields(self) -> None:
        rule = make_monitor("eDP-1", scale=1.5).to_rule()
        text = lua.rule_to_lua(rule)
        for field in ("output", "mode", "position", "scale", "transform", "mirror", "disabled"):
            self.assertIn(f"{field} =", text)
        self.assertIn('output = "eDP-1"', text)
        self.assertIn("scale = 1.5", text)
        self.assertIn("disabled = false", text)

    def test_rule_to_lua_escapes_mirror(self) -> None:
        rule = make_monitor("HDMI-A-1", mirror='eDP"1').to_rule()
        self.assertIn('mirror = "eDP\\"1"', lua.rule_to_lua(rule))

    def test_rules_to_eval_wraps_in_do_block(self) -> None:
        rules = [make_monitor("eDP-1").to_rule()]
        code = lua.rules_to_eval(rules)
        self.assertTrue(code.startswith("do\n"))
        self.assertTrue(code.rstrip().endswith("end"))
        self.assertIn("hl.monitor({", code)
        self.assertEqual(code.count("hl.monitor("), 1)

    def test_rules_to_eval_multiple(self) -> None:
        rules = [
            make_monitor("eDP-1").to_rule(),
            make_monitor("HDMI-A-1", x=1280).to_rule(),
        ]
        code = lua.rules_to_eval(rules)
        self.assertEqual(code.count("hl.monitor("), 2)
        self.assertIn('position = "1280x0"', code)


class GenerateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.monitors = [make_monitor("eDP-1"), make_monitor("HDMI-A-1", x=1280)]
        self.profile = profiles.Profile.from_monitors(
            "Escritorio", self.monitors, primary="eDP-1"
        )
        self.state = profiles.State(
            active_profile="Escritorio",
            primary="eDP-1",
            current_rules=[monitor.to_rule() for monitor in self.monitors],
        )

    def test_generate_contains_current_and_profile(self) -> None:
        text = lua.generate([self.profile], self.state)
        self.assertIn("local current = {", text)
        self.assertIn('name = "Escritorio"', text)
        self.assertIn("fingerprint = \"Monitor eDP-1|serial-eDP-1\"", text)
        self.assertIn("auto = true", text)
        self.assertIn('hl.on("monitor.added"', text)
        self.assertIn('hl.on("monitor.removed"', text)
        self.assertIn('hl.on("hyprland.start"', text)

    def test_generate_escapes_profile_name(self) -> None:
        profile = profiles.Profile.from_monitors('Mi "perfil"', self.monitors)
        text = lua.generate([profile], self.state)
        self.assertIn('name = "Mi \\"perfil\\""', text)

    def test_generate_empty_state(self) -> None:
        text = lua.generate([], profiles.State())
        self.assertIn("local current = {\n}", text)
        self.assertIn("local profiles = {\n}", text)

    def test_generated_lua_has_valid_syntax(self) -> None:
        luac = shutil.which("luac") or shutil.which("luac5.4")
        if not luac:
            self.skipTest("luac no está instalado")

        text = lua.generate([self.profile], self.state)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor-profiles.lua"
            path.write_text(text, encoding="utf-8")
            result = subprocess.run(
                [luac, "-p", str(path)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
