"""Pruebas de la capa hyprctl: parseo de monitores y resolución de espejos."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from hyprdisplay import hypr


def raw_monitor(**overrides) -> dict:
    data = {
        "id": 0,
        "name": "eDP-1",
        "description": "BOE 0x09DE",
        "serial": "0x00000000",
        "make": "BOE",
        "model": "0x09DE",
        "width": 1920,
        "height": 1080,
        "refreshRate": 60.001,
        "x": 0,
        "y": 0,
        "scale": 1.5,
        "transform": 0,
        "disabled": False,
        "mirrorOf": "none",
        "focused": True,
        "vrr": False,
        "physicalWidth": 344,
        "physicalHeight": 194,
        "availableModes": ["1920x1080@60.001Hz", "1920x1080@60.00Hz"],
        "activeWorkspace": {"id": 1},
    }
    data.update(overrides)
    return data


class MonitorParsingTests(unittest.TestCase):
    def test_from_json(self) -> None:
        monitor = hypr.Monitor.from_json(raw_monitor())
        self.assertEqual(monitor.name, "eDP-1")
        self.assertEqual((monitor.width, monitor.height), (1920, 1080))
        self.assertAlmostEqual(monitor.refresh_rate, 60.001)
        self.assertAlmostEqual(monitor.scale, 1.5)
        self.assertEqual(monitor.fingerprint, "BOE 0x09DE|0x00000000")
        self.assertEqual(len(monitor.available_modes), 2)

    def test_from_json_without_modes_uses_current(self) -> None:
        monitor = hypr.Monitor.from_json(raw_monitor(availableModes=[]))
        self.assertEqual(len(monitor.available_modes), 1)
        self.assertEqual(monitor.available_modes[0].width, 1920)

    def test_from_json_empty(self) -> None:
        monitor = hypr.Monitor.from_json({})
        self.assertEqual(monitor.name, "")
        self.assertEqual(monitor.mirror_of, "none")
        self.assertEqual(monitor.available_modes, [])


class MirrorResolutionTests(unittest.TestCase):
    def test_numeric_id_resolved_to_name(self) -> None:
        data = [
            raw_monitor(id=0, name="eDP-1", mirrorOf="none"),
            raw_monitor(id=1, name="HDMI-A-1", mirrorOf="0"),
        ]
        monitors = [hypr.Monitor.from_json(item) for item in data]
        hypr.resolve_mirror_names(monitors, data)
        self.assertEqual(monitors[0].mirror_of, "")
        self.assertEqual(monitors[1].mirror_of, "eDP-1")

    def test_named_mirror_is_kept(self) -> None:
        data = [
            raw_monitor(id=0, name="eDP-1", mirrorOf="none"),
            raw_monitor(id=1, name="HDMI-A-1", mirrorOf="eDP-1"),
        ]
        monitors = [hypr.Monitor.from_json(item) for item in data]
        hypr.resolve_mirror_names(monitors, data)
        self.assertEqual(monitors[1].mirror_of, "eDP-1")

    def test_unknown_id_is_cleared(self) -> None:
        data = [
            raw_monitor(id=0, name="eDP-1", mirrorOf="7"),
        ]
        monitors = [hypr.Monitor.from_json(item) for item in data]
        hypr.resolve_mirror_names(monitors, data)
        self.assertEqual(monitors[0].mirror_of, "")

    def test_none_becomes_empty(self) -> None:
        data = [raw_monitor(mirrorOf="none")]
        monitors = [hypr.Monitor.from_json(item) for item in data]
        hypr.resolve_mirror_names(monitors, data)
        self.assertEqual(monitors[0].mirror_of, "")


class VersionTests(unittest.TestCase):
    def test_parse_plain(self) -> None:
        self.assertEqual(hypr.parse_version("0.56.2"), (0, 56, 2))

    def test_parse_tag(self) -> None:
        self.assertEqual(hypr.parse_version("v0.55"), (0, 55))

    def test_parse_empty(self) -> None:
        self.assertEqual(hypr.parse_version(""), ())
        self.assertEqual(hypr.parse_version(None), ())

    def test_supported(self) -> None:
        ok, detail = hypr.version_supported({"version": "0.56.2"})
        self.assertTrue(ok)
        self.assertIn("0.56.2", detail)

    def test_too_old(self) -> None:
        ok, detail = hypr.version_supported({"version": "0.54.1"})
        self.assertFalse(ok)
        self.assertIn("0.55+", detail)

    def test_unknown_version(self) -> None:
        ok, _ = hypr.version_supported({})
        self.assertFalse(ok)


class WaylandOutputsTests(unittest.TestCase):
    def test_without_graphical_session(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(hypr.wayland_outputs())


if __name__ == "__main__":
    unittest.main()
