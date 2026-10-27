"""Canvas interactivo para arrastrar y ordenar monitores."""

from __future__ import annotations

import math
import time
from typing import Callable

import cairo
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import layout  # noqa: E402

BACKGROUND = (0.078, 0.078, 0.094)
GRID = (1.0, 1.0, 1.0, 0.045)
TEXT = (0.965, 0.961, 0.957)
TEXT_DIM = (0.75, 0.745, 0.729)
MONITOR_FILL = (0.36, 0.35, 0.38, 0.55)
MONITOR_BORDER = (0.61, 0.60, 0.58)
PRIMARY_BORDER = (0.21, 0.52, 0.89)
PRIMARY_FILL = (0.21, 0.52, 0.89, 0.22)
SELECTED_BORDER = (0.15, 0.64, 0.41)
OVERLAP_BORDER = (0.88, 0.11, 0.14)
OVERLAP_FILL = (0.88, 0.11, 0.14, 0.16)
MIRROR_BORDER = (0.96, 0.65, 0.14)


def _rounded_rect(cr: cairo.Context, x: float, y: float, width: float, height: float, radius: float) -> None:
    radius = max(0.0, min(radius, width / 2, height / 2))
    cr.new_sub_path()
    cr.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
    cr.arc(x + width - radius, y + radius, radius, 1.5 * math.pi, 2 * math.pi)
    cr.arc(x + width - radius, y + height - radius, radius, 0, 0.5 * math.pi)
    cr.arc(x + radius, y + height - radius, radius, 0.5 * math.pi, math.pi)
    cr.close_path()


def _text(
    cr: cairo.Context,
    text: str,
    x: float,
    y: float,
    size: float = 13,
    color: tuple[float, ...] = TEXT,
    bold: bool = False,
    centered: bool = False,
) -> None:
    cr.select_font_face(
        "Sans",
        cairo.FONT_SLANT_NORMAL,
        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
    )
    cr.set_font_size(size)
    cr.set_source_rgba(*color)
    if centered:
        extents = cr.text_extents(text)
        x -= extents.width / 2 + extents.x_bearing
        y -= extents.height / 2 + extents.y_bearing
    cr.move_to(x, y)
    cr.show_text(text)


class MonitorCanvas(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.monitors: list[layout.MonitorState] = []
        self.primary = ""
        self.selected = ""
        self.on_change: Callable[[layout.MonitorState, bool], None] | None = None
        self.identify_until = 0.0

        self._zoom = 0.2
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._drag: dict | None = None

        self.set_draw_func(self._draw)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_content_width(360)
        self.set_content_height(320)

        gesture = Gtk.GestureDrag()
        gesture.set_button(1)
        gesture.connect("drag-begin", self._on_drag_begin)
        gesture.connect("drag-update", self._on_drag_update)
        gesture.connect("drag-end", self._on_drag_end)
        self.add_controller(gesture)

    # ------------------------------------------------------------------ API

    def set_monitors(self, monitors: list[layout.MonitorState], primary: str) -> None:
        self.monitors = monitors
        self.primary = primary
        self.queue_draw()

    def identify(self) -> None:
        self.identify_until = time.monotonic() + 2.5
        self.queue_draw()
        GLib.timeout_add(2600, self._clear_identify)

    def _clear_identify(self) -> bool:
        self.identify_until = 0.0
        self.queue_draw()
        return False

    # -------------------------------------------------------------- helpers

    def _get(self, name: str) -> layout.MonitorState | None:
        for monitor in self.monitors:
            if monitor.name == name:
                return monitor
        return None

    def _fit(self, width: int, height: int) -> None:
        active = [monitor for monitor in self.monitors if not monitor.disabled]
        if not active or width <= 0 or height <= 0:
            self._zoom = 1.0
            self._offset_x = 0.0
            self._offset_y = 0.0
            return

        rects = [monitor.rect() for monitor in active]
        min_x = min(rect.x for rect in rects)
        min_y = min(rect.y for rect in rects)
        max_x = max(rect.right for rect in rects)
        max_y = max(rect.bottom for rect in rects)
        world_width = max(1, max_x - min_x)
        world_height = max(1, max_y - min_y)

        margin = 52
        zoom = min(
            (width - 2 * margin) / world_width,
            (height - 2 * margin) / world_height,
            1.0,
        )
        self._zoom = max(0.02, zoom)
        self._offset_x = (width - world_width * self._zoom) / 2 - min_x * self._zoom
        self._offset_y = (height - world_height * self._zoom) / 2 - min_y * self._zoom

    def _world_to_screen(self, x: float, y: float) -> tuple[float, float]:
        return x * self._zoom + self._offset_x, y * self._zoom + self._offset_y

    def _screen_to_world(self, x: float, y: float) -> tuple[float, float]:
        if self._zoom <= 0:
            return 0.0, 0.0
        return (x - self._offset_x) / self._zoom, (y - self._offset_y) / self._zoom

    def _overlapping(self) -> set[str]:
        active = [m for m in self.monitors if not m.disabled and not m.mirror]
        names: set[str] = set()
        for index, first in enumerate(active):
            for second in active[index + 1:]:
                if first.rect().intersects(second.rect()):
                    names.update((first.name, second.name))
        return names

    # ---------------------------------------------------------------- draw

    def _draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, width: int, height: int) -> None:
        cr.set_source_rgb(*BACKGROUND)
        cr.paint()

        self._fit(width, height)
        self._draw_grid(cr, width, height)

        active = [monitor for monitor in self.monitors if not monitor.disabled]
        if not active:
            _text(
                cr,
                "Sin monitores activos",
                width / 2,
                height / 2,
                18,
                TEXT_DIM,
                centered=True,
            )
            return

        overlapping = self._overlapping()
        for index, monitor in enumerate(active):
            self._draw_monitor(cr, monitor, index, monitor.name in overlapping)

        if time.monotonic() < self.identify_until:
            for index, monitor in enumerate(active, start=1):
                x, y = self._world_to_screen(monitor.x, monitor.y)
                rect = monitor.rect()
                cr.set_source_rgba(0.0, 0.0, 0.0, 0.55)
                cr.rectangle(x, y, rect.w * self._zoom, rect.h * self._zoom)
                cr.fill()
                _text(
                    cr,
                    str(index),
                    x + rect.w * self._zoom / 2,
                    y + rect.h * self._zoom / 2,
                    max(28, min(96, rect.h * self._zoom / 2)),
                    TEXT,
                    bold=True,
                    centered=True,
                )

        disabled = len(self.monitors) - len(active)
        if disabled:
            _text(
                cr,
                f"{disabled} monitor(es) desactivado(s)",
                width - 16,
                height - 14,
                12,
                TEXT_DIM,
            )

    def _draw_grid(self, cr: cairo.Context, width: int, height: int) -> None:
        step = 100
        while step * self._zoom < 22:
            step *= 2

        min_x, min_y = self._screen_to_world(0, 0)
        max_x, max_y = self._screen_to_world(width, height)
        start_x = math.floor(min_x / step) * step
        start_y = math.floor(min_y / step) * step

        cr.set_source_rgba(*GRID)
        cr.set_line_width(1)
        x = start_x
        while x <= max_x:
            sx, _ = self._world_to_screen(x, 0)
            cr.move_to(sx, 0)
            cr.line_to(sx, height)
            x += step
        y = start_y
        while y <= max_y:
            _, sy = self._world_to_screen(0, y)
            cr.move_to(0, sy)
            cr.line_to(width, sy)
            y += step
        cr.stroke()

    def _draw_monitor(
        self,
        cr: cairo.Context,
        monitor: layout.MonitorState,
        index: int,
        overlaps: bool,
    ) -> None:
        rect = monitor.rect()
        x, y = self._world_to_screen(rect.x, rect.y)
        w = rect.w * self._zoom
        h = rect.h * self._zoom

        if w < 2 or h < 2:
            return

        if overlaps:
            fill = OVERLAP_FILL
            border = OVERLAP_BORDER
        elif monitor.primary:
            fill = PRIMARY_FILL
            border = PRIMARY_BORDER
        elif monitor.mirror:
            fill = MONITOR_FILL
            border = MIRROR_BORDER
        elif monitor.name == self.selected:
            fill = MONITOR_FILL
            border = SELECTED_BORDER
        else:
            fill = MONITOR_FILL
            border = MONITOR_BORDER

        _rounded_rect(cr, x, y, w, h, min(14, w / 8, h / 8))
        cr.set_source_rgba(*fill)
        cr.fill_preserve()
        cr.set_source_rgba(*border)
        cr.set_line_width(2.5 if monitor.primary or overlaps else 1.8)
        cr.stroke()

        # Número del monitor
        badge_radius = 14
        badge_x = x + w - badge_radius - 10
        badge_y = y + badge_radius + 10
        if w > 2 * badge_radius + 20:
            cr.set_source_rgba(*border)
            cr.arc(badge_x, badge_y, badge_radius, 0, 2 * math.pi)
            cr.fill()
            _text(
                cr,
                str(index + 1),
                badge_x,
                badge_y,
                13,
                BACKGROUND,
                bold=True,
                centered=True,
            )

        if w < 70 or h < 34:
            return

        padding = 14
        _text(cr, monitor.name, x + padding, y + 24, min(17, max(11, w / 12)), TEXT, bold=True)

        if h >= 58:
            mode = f"{monitor.width}×{monitor.height} @ {monitor.refresh:g} Hz"
            _text(cr, mode, x + padding, y + 44, 12, TEXT_DIM)

        if h >= 82:
            details = f"Escala {monitor.scale * 100:g} %"
            if monitor.transform:
                details += f" · {monitor.transform * 90}°"
            _text(cr, details, x + padding, y + 62, 11, TEXT_DIM)

        if monitor.mirror and h >= 106:
            _text(cr, f"Espejo de {monitor.mirror}", x + padding, y + 80, 11, MIRROR_BORDER)

        if h >= 128:
            _text(cr, f"Posición {monitor.x}×{monitor.y}", x + padding, y + h - 12, 11, TEXT_DIM)

        if overlaps and h >= 150:
            _text(cr, "⚠ solapamiento", x + padding, y + h - 30, 11, OVERLAP_BORDER, bold=True)

    # ---------------------------------------------------------------- drag

    def _on_drag_begin(self, _gesture: Gtk.GestureDrag, start_x: float, start_y: float) -> None:
        self._fit(self.get_width(), self.get_height())
        world_x, world_y = self._screen_to_world(start_x, start_y)

        for monitor in reversed(self.monitors):
            if monitor.disabled:
                continue
            rect = monitor.rect()
            if rect.x <= world_x <= rect.right and rect.y <= world_y <= rect.bottom:
                self.selected = monitor.name
                self._drag = {
                    "name": monitor.name,
                    "origin_x": monitor.x,
                    "origin_y": monitor.y,
                    "moved": False,
                }
                self.queue_draw()
                return
        self._drag = None

    def _on_drag_update(self, _gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if not self._drag:
            return
        monitor = self._get(self._drag["name"])
        if monitor is None:
            return

        monitor.x = round(self._drag["origin_x"] + offset_x / self._zoom)
        monitor.y = round(self._drag["origin_y"] + offset_y / self._zoom)

        others = [
            other.rect()
            for other in self.monitors
            if other.name != monitor.name and not other.disabled and not other.mirror
        ]
        threshold = max(8, min(80, round(14 / self._zoom)))
        monitor.x, monitor.y = layout.snap_position(monitor.rect(), others, threshold=threshold)

        self._drag["moved"] = True
        self.queue_draw()
        if self.on_change:
            self.on_change(monitor, False)

    def _on_drag_end(self, _gesture: Gtk.GestureDrag, _offset_x: float, _offset_y: float) -> None:
        if self._drag and self._drag.get("moved") and self.on_change:
            monitor = self._get(self._drag["name"])
            if monitor is not None:
                self.on_change(monitor, True)
        self._drag = None
