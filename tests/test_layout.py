"""Pruebas de geometría, validación y modos rápidos."""

from __future__ import annotations

import unittest

from hyprdisplay import layout
from hyprdisplay.hypr import Mode


def make_monitor(
    name: str,
    *,
    width: int = 1920,
    height: int = 1080,
    refresh: float = 60.0,
    x: int = 0,
    y: int = 0,
    scale: float = 1.0,
    transform: int = 0,
    mirror: str = "",
    disabled: bool = False,
    primary: bool = False,
    modes: list[Mode] | None = None,
) -> layout.MonitorState:
    return layout.MonitorState(
        name=name,
        description=f"Monitor {name}",
        serial=f"serial-{name}",
        available_modes=list(modes or [Mode(width, height, refresh)]),
        width=width,
        height=height,
        refresh=refresh,
        x=x,
        y=y,
        scale=scale,
        transform=transform,
        mirror=mirror,
        disabled=disabled,
        primary=primary,
    )


class ModeTests(unittest.TestCase):
    def test_parse_valid(self) -> None:
        mode = Mode.parse("1920x1080@59.94Hz")
        self.assertIsNotNone(mode)
        assert mode is not None
        self.assertEqual((mode.width, mode.height), (1920, 1080))
        self.assertAlmostEqual(mode.refresh, 59.94)

    def test_parse_invalid(self) -> None:
        self.assertIsNone(Mode.parse("1920x1080"))
        self.assertIsNone(Mode.parse("hola"))

    def test_mode_string(self) -> None:
        self.assertEqual(Mode(2560, 1440, 165.0).mode_string, "2560x1440@165")
        self.assertEqual(Mode(1920, 1080, 59.94).label, "1920×1080 @ 59.94 Hz")


class GeometryTests(unittest.TestCase):
    def test_logical_size_with_scale(self) -> None:
        monitor = make_monitor("eDP-1", scale=1.5)
        self.assertEqual(monitor.logical_size(), (1280, 720))

    def test_logical_size_rotated(self) -> None:
        monitor = make_monitor("HDMI-A-1", width=2560, height=1440, transform=1)
        self.assertEqual(monitor.logical_size(), (1440, 2560))

    def test_rect(self) -> None:
        monitor = make_monitor("HDMI-A-1", x=1280, y=0)
        rect = monitor.rect()
        self.assertEqual((rect.x, rect.y, rect.w, rect.h), (1280, 0, 1920, 1080))

    def test_intersects(self) -> None:
        first = layout.Rect(0, 0, 100, 100)
        self.assertTrue(first.intersects(layout.Rect(50, 50, 100, 100)))
        self.assertFalse(first.intersects(layout.Rect(100, 0, 100, 100)))
        self.assertFalse(first.intersects(layout.Rect(0, 100, 100, 100)))

    def test_intersection_area(self) -> None:
        first = layout.Rect(0, 0, 100, 100)
        self.assertEqual(first.intersection_area(layout.Rect(50, 50, 100, 100)), 2500)
        self.assertEqual(first.intersection_area(layout.Rect(200, 200, 10, 10)), 0)


class ValidationTests(unittest.TestCase):
    def test_no_active_monitors(self) -> None:
        errors = layout.validate([make_monitor("eDP-1", disabled=True)])
        self.assertTrue(errors)

    def test_overlap_detected(self) -> None:
        monitors = [
            make_monitor("eDP-1"),
            make_monitor("HDMI-A-1", x=100),
        ]
        errors = layout.validate(monitors)
        self.assertTrue(any("solapan" in error for error in errors))

    def test_touching_is_valid(self) -> None:
        monitors = [
            make_monitor("eDP-1"),
            make_monitor("HDMI-A-1", x=1920),
        ]
        self.assertEqual(layout.validate(monitors), [])

    def test_disabled_monitor_ignored(self) -> None:
        monitors = [
            make_monitor("eDP-1"),
            make_monitor("HDMI-A-1", x=100, disabled=True),
        ]
        self.assertEqual(layout.validate(monitors), [])

    def test_invalid_scale(self) -> None:
        monitors = [make_monitor("eDP-1", scale=1.4)]
        errors = layout.validate(monitors)
        self.assertTrue(any("escala" in error for error in errors))

    def test_valid_scale(self) -> None:
        monitors = [make_monitor("eDP-1", scale=1.5)]
        self.assertEqual(layout.validate(monitors), [])

    def test_mirror_ignored_for_overlap(self) -> None:
        monitors = [
            make_monitor("eDP-1"),
            make_monitor("HDMI-A-1", x=0, mirror="eDP-1"),
        ]
        self.assertEqual(layout.validate(monitors), [])

    def test_mirror_missing_target(self) -> None:
        monitors = [make_monitor("HDMI-A-1", mirror="eDP-1")]
        errors = layout.validate(monitors)
        self.assertTrue(any("no existe" in error for error in errors))

    def test_mirror_chain_rejected(self) -> None:
        monitors = [
            make_monitor("eDP-1"),
            make_monitor("HDMI-A-1", mirror="eDP-1"),
            make_monitor("DP-1", mirror="HDMI-A-1"),
        ]
        errors = layout.validate(monitors)
        self.assertTrue(any("cadenas" in error for error in errors))

    def test_warnings_for_different_mode(self) -> None:
        monitors = [
            make_monitor("eDP-1"),
            make_monitor("HDMI-A-1", width=1280, height=720, mirror="eDP-1"),
        ]
        result = layout.warnings(monitors)
        self.assertTrue(any("resolución" in warning for warning in result))


class ScaleTests(unittest.TestCase):
    def test_valid_scales(self) -> None:
        self.assertIn(1.5, layout.valid_scales(1920, 1080))
        self.assertNotIn(1.4, layout.valid_scales(1920, 1080))

    def test_is_valid_scale(self) -> None:
        self.assertTrue(layout.is_valid_scale(1920, 1.5))
        self.assertFalse(layout.is_valid_scale(1920, 1.4))
        self.assertFalse(layout.is_valid_scale(0, 1.0))


class QuickModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.monitors = [
            make_monitor("eDP-1", primary=True),
            make_monitor("HDMI-A-1", x=1920),
        ]

    def test_internal_disables_external(self) -> None:
        result = layout.quick_mode("internal", self.monitors)
        by_name = {monitor.name: monitor for monitor in result}
        self.assertFalse(by_name["eDP-1"].disabled)
        self.assertTrue(by_name["HDMI-A-1"].disabled)
        self.assertTrue(by_name["eDP-1"].primary)
        self.assertEqual(layout.validate(result), [])

    def test_external_disables_internal(self) -> None:
        result = layout.quick_mode("external", self.monitors)
        by_name = {monitor.name: monitor for monitor in result}
        self.assertTrue(by_name["eDP-1"].disabled)
        self.assertFalse(by_name["HDMI-A-1"].disabled)
        self.assertEqual((by_name["HDMI-A-1"].x, by_name["HDMI-A-1"].y), (0, 0))

    def test_duplicate_mirrors_external(self) -> None:
        result = layout.quick_mode("duplicate", self.monitors, primary="eDP-1")
        by_name = {monitor.name: monitor for monitor in result}
        self.assertEqual(by_name["HDMI-A-1"].mirror, "eDP-1")
        self.assertEqual(by_name["eDP-1"].mirror, "")
        self.assertEqual((by_name["HDMI-A-1"].x, by_name["HDMI-A-1"].y), (0, 0))
        self.assertEqual(by_name["HDMI-A-1"].scale, by_name["eDP-1"].scale)
        self.assertEqual(layout.validate(result), [])

    def test_extend_lays_out_side_by_side(self) -> None:
        result = layout.quick_mode("extend", self.monitors, primary="eDP-1")
        by_name = {monitor.name: monitor for monitor in result}
        self.assertEqual((by_name["eDP-1"].x, by_name["eDP-1"].y), (0, 0))
        self.assertEqual(by_name["HDMI-A-1"].x, by_name["eDP-1"].rect().right)
        self.assertFalse(by_name["HDMI-A-1"].disabled)
        self.assertEqual(layout.validate(result), [])

    def test_internal_without_internal_monitor(self) -> None:
        with self.assertRaises(ValueError):
            layout.quick_mode("internal", [make_monitor("HDMI-A-1")])

    def test_external_without_external_monitor(self) -> None:
        with self.assertRaises(ValueError):
            layout.quick_mode("external", [make_monitor("eDP-1")])

    def test_unknown_mode(self) -> None:
        with self.assertRaises(ValueError):
            layout.quick_mode("otro", self.monitors)

    def test_detect_mode(self) -> None:
        self.assertEqual(layout.detect_mode([make_monitor("eDP-1")]), "internal")
        self.assertEqual(layout.detect_mode([make_monitor("HDMI-A-1")]), "external")
        self.assertEqual(layout.detect_mode(self.monitors), "extend")
        self.assertEqual(
            layout.detect_mode([self.monitors[0], make_monitor("HDMI-A-1", mirror="eDP-1")]),
            "duplicate",
        )

    def test_next_mode_cycles(self) -> None:
        self.assertEqual(layout.next_mode("internal"), "duplicate")
        self.assertEqual(layout.next_mode("duplicate"), "extend")
        self.assertEqual(layout.next_mode("extend"), "external")
        self.assertEqual(layout.next_mode("external"), "internal")
        self.assertEqual(layout.next_mode("desconocido"), "extend")


class SnappingTests(unittest.TestCase):
    def test_snap_to_neighbour_edge(self) -> None:
        rect = layout.Rect(1914, 3, 1920, 1080)
        others = [layout.Rect(0, 0, 1920, 1080)]
        self.assertEqual(layout.snap_position(rect, others, threshold=16), (1920, 0))

    def test_snap_to_origin(self) -> None:
        rect = layout.Rect(5, -4, 100, 100)
        self.assertEqual(layout.snap_position(rect, [], threshold=16), (0, 0))

    def test_no_snap_when_far(self) -> None:
        rect = layout.Rect(500, 500, 100, 100)
        self.assertEqual(layout.snap_position(rect, [], threshold=16), (500, 500))


class RuleTests(unittest.TestCase):
    def test_rule_round_trip(self) -> None:
        monitor = make_monitor("HDMI-A-1", x=1280, scale=1.0, transform=1, mirror="")
        rule = monitor.to_rule()
        self.assertEqual(rule["output"], "HDMI-A-1")
        self.assertEqual(rule["position"], "1280x0")
        self.assertEqual(rule["mode"], "1920x1080@60")
        updated = layout.monitors_from_rules([monitor], [rule])[0]
        self.assertEqual((updated.x, updated.y), (1280, 0))
        self.assertEqual(updated.transform, 1)

    def test_rule_round_trip_negative_position(self) -> None:
        monitor = make_monitor("HDMI-A-1", x=-1920, y=-120)
        updated = layout.monitors_from_rules([monitor], [monitor.to_rule()])[0]
        self.assertEqual((updated.x, updated.y), (-1920, -120))

    def test_rule_key_ignores_dict_order(self) -> None:
        first = {"output": "eDP-1", "mode": "1920x1080@60", "position": "0x0", "scale": 1.5,
                 "transform": 0, "mirror": "", "disabled": False}
        second = dict(reversed(list(first.items())))
        self.assertTrue(layout.rules_equal([first], [second]))

    def test_rules_equal_detects_difference(self) -> None:
        first = make_monitor("eDP-1").to_rule()
        second = dict(first, position="10x0")
        self.assertFalse(layout.rules_equal([first], [second]))

    def test_find_mode_prefers_nearest_refresh(self) -> None:
        modes = [Mode(1920, 1080, 60.0), Mode(1920, 1080, 120.0)]
        self.assertEqual(layout.find_mode(modes, 1920, 1080, 120.0), modes[1])
        self.assertEqual(layout.find_mode(modes, 1920, 1080, 119.9), modes[1])
        self.assertIsNone(layout.find_mode(modes, 1280, 720, 60.0))

    def test_parse_mode_string(self) -> None:
        self.assertEqual(layout.parse_mode_string("2560x1440@144"), (2560, 1440, 144.0))
        self.assertEqual(layout.parse_mode_string("1920x1080"), (1920, 1080, 60.0))
        self.assertIsNone(layout.parse_mode_string("preferred"))


if __name__ == "__main__":
    unittest.main()
