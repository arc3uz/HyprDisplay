"""Geometría de la disposición de monitores y modos rápidos."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Iterable

from .hypr import Mode, Monitor

DEFAULT_SCALES = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
QUICK_MODES = ("internal", "duplicate", "extend", "external")
QUICK_MODE_LABELS = {
    "internal": "Solo portátil",
    "duplicate": "Duplicar",
    "extend": "Extender",
    "external": "Solo externo",
}

_MODE_STRING_RE = re.compile(r"^(\d+)x(\d+)(?:@([0-9.]+))?$")


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )

    def intersection_area(self, other: "Rect") -> int:
        if not self.intersects(other):
            return 0
        width = min(self.right, other.right) - max(self.x, other.x)
        height = min(self.bottom, other.bottom) - max(self.y, other.y)
        return max(0, width) * max(0, height)


@dataclass
class MonitorState:
    name: str
    description: str
    make: str = ""
    model: str = ""
    serial: str = ""
    physical_width: int = 0
    physical_height: int = 0
    available_modes: list[Mode] = field(default_factory=list)
    width: int = 0
    height: int = 0
    refresh: float = 60.0
    x: int = 0
    y: int = 0
    scale: float = 1.0
    transform: int = 0
    mirror: str = ""
    disabled: bool = False
    primary: bool = False
    focused: bool = False
    active_workspace: int = 0

    @property
    def fingerprint(self) -> str:
        return f"{self.description}|{self.serial}"

    @property
    def is_internal(self) -> bool:
        return self.name.lower().startswith(("edp", "lvds", "dsi"))

    @property
    def mode_string(self) -> str:
        if self.width > 0 and self.height > 0:
            return f"{self.width}x{self.height}@{self.refresh:g}"
        return "preferred"

    def logical_size(self) -> tuple[int, int]:
        if self.width <= 0 or self.height <= 0 or self.scale <= 0:
            return (0, 0)
        width = self.width / self.scale
        height = self.height / self.scale
        if self.transform % 2 == 1:
            width, height = height, width
        return (max(1, round(width)), max(1, round(height)))

    def rect(self) -> Rect:
        width, height = self.logical_size()
        return Rect(int(self.x), int(self.y), width, height)

    def to_rule(self) -> dict:
        return {
            "output": self.name,
            "mode": self.mode_string,
            "position": f"{int(self.x)}x{int(self.y)}",
            "scale": round(float(self.scale), 4),
            "transform": int(self.transform),
            "mirror": self.mirror or "",
            "disabled": bool(self.disabled),
        }

    def copy(self) -> "MonitorState":
        return replace(self, available_modes=list(self.available_modes))

    @classmethod
    def from_monitor(cls, monitor: Monitor, primary: str | None = None) -> "MonitorState":
        return cls(
            name=monitor.name,
            description=monitor.description,
            make=monitor.make,
            model=monitor.model,
            serial=monitor.serial,
            physical_width=monitor.physical_width,
            physical_height=monitor.physical_height,
            available_modes=list(monitor.available_modes),
            width=monitor.width,
            height=monitor.height,
            refresh=monitor.refresh_rate,
            x=monitor.x,
            y=monitor.y,
            scale=monitor.scale,
            transform=monitor.transform,
            mirror="" if monitor.mirror_of in ("", "none") else monitor.mirror_of,
            disabled=monitor.disabled,
            primary=(monitor.name == primary),
            focused=monitor.focused,
            active_workspace=monitor.active_workspace,
        )


def from_monitors(monitors: Iterable[Monitor], primary: str | None = None) -> list[MonitorState]:
    return [MonitorState.from_monitor(monitor, primary) for monitor in monitors]


def enabled(monitors: Iterable[MonitorState]) -> list[MonitorState]:
    return [monitor for monitor in monitors if not monitor.disabled]


def is_valid_scale(size: int, scale: float) -> bool:
    if size <= 0 or scale <= 0:
        return False
    value = size / scale
    return abs(value - round(value)) < 1e-6


def valid_scales(width: int, height: int, candidates: Iterable[float] = DEFAULT_SCALES) -> list[float]:
    return [scale for scale in candidates if is_valid_scale(width, scale) and is_valid_scale(height, scale)]


def primary_name(monitors: Iterable[MonitorState]) -> str:
    monitors = list(monitors)
    for monitor in monitors:
        if monitor.primary and not monitor.disabled:
            return monitor.name
    for monitor in monitors:
        if not monitor.disabled:
            return monitor.name
    return monitors[0].name if monitors else ""


def ensure_primary(monitors: list[MonitorState], name: str | None) -> str:
    chosen = name if name and any(m.name == name and not m.disabled for m in monitors) else primary_name(monitors)
    for monitor in monitors:
        monitor.primary = monitor.name == chosen
    return chosen


def validate(monitors: Iterable[MonitorState]) -> list[str]:
    monitors = list(monitors)
    active = enabled(monitors)
    errors: list[str] = []

    if not active:
        return ["Debe haber al menos un monitor activo."]

    for monitor in active:
        if monitor.width <= 0 or monitor.height <= 0:
            errors.append(f"{monitor.name}: la resolución no es válida.")
        if not is_valid_scale(monitor.width, monitor.scale) or not is_valid_scale(monitor.height, monitor.scale):
            errors.append(
                f"{monitor.name}: la escala {monitor.scale:g} no produce píxeles lógicos enteros."
            )
        rect = monitor.rect()
        if rect.w <= 0 or rect.h <= 0:
            errors.append(f"{monitor.name}: el tamaño lógico no es válido.")

    # Los monitores en espejo no ocupan espacio en el layout.
    layout_monitors = [monitor for monitor in active if not monitor.mirror]
    for index, first in enumerate(layout_monitors):
        for second in layout_monitors[index + 1:]:
            if first.rect().intersects(second.rect()):
                errors.append(f"{first.name} y {second.name} se solapan.")

    by_name = {monitor.name: monitor for monitor in monitors}
    for monitor in active:
        if not monitor.mirror:
            continue
        target = by_name.get(monitor.mirror)
        if target is None:
            errors.append(f"{monitor.name}: el monitor de espejo «{monitor.mirror}» no existe.")
        elif target.disabled:
            errors.append(f"{monitor.name}: el monitor de espejo «{monitor.mirror}» está desactivado.")
        elif target.name == monitor.name:
            errors.append(f"{monitor.name}: un monitor no puede reflejarse a sí mismo.")
        elif target.mirror:
            errors.append(
                f"{monitor.name}: no se permiten cadenas de espejos ({target.name} ya es un espejo)."
            )

    return errors


def warnings(monitors: Iterable[MonitorState]) -> list[str]:
    monitors = list(monitors)
    by_name = {monitor.name: monitor for monitor in monitors}
    result: list[str] = []

    for monitor in enabled(monitors):
        if not monitor.mirror:
            continue
        target = by_name.get(monitor.mirror)
        if target is None or target.disabled:
            continue
        if (monitor.width, monitor.height) != (target.width, target.height):
            result.append(
                f"{monitor.name}: el espejo tiene una resolución distinta a {target.name}; "
                "Hyprland podría estirar la imagen."
            )
        if abs(monitor.scale - target.scale) > 1e-6:
            result.append(
                f"{monitor.name}: el espejo tiene una escala distinta a {target.name}."
            )

    return result


def snap_position(rect: Rect, others: Iterable[Rect], threshold: int = 16) -> tuple[int, int]:
    """Ajusta la posición a los bordes de otros monitores y al origen."""
    xs = {0}
    ys = {0}
    for other in others:
        xs.update((other.x, other.right, other.x - rect.w, other.right - rect.w))
        ys.update((other.y, other.bottom, other.y - rect.h, other.bottom - rect.h))

    x, y = rect.x, rect.y
    nearest_x = min(xs, key=lambda value: abs(value - x))
    if abs(nearest_x - x) <= threshold:
        x = nearest_x
    nearest_y = min(ys, key=lambda value: abs(value - y))
    if abs(nearest_y - y) <= threshold:
        y = nearest_y
    return int(x), int(y)


def _set_primary(monitors: list[MonitorState], name: str) -> None:
    for monitor in monitors:
        monitor.primary = monitor.name == name


def quick_mode(
    mode: str,
    monitors: Iterable[MonitorState],
    primary: str | None = None,
) -> list[MonitorState]:
    """Calcula una disposición tipo Win+P sin aplicarla."""
    result = [monitor.copy() for monitor in monitors]
    internal = [monitor for monitor in result if monitor.is_internal]
    external = [monitor for monitor in result if not monitor.is_internal]
    current_primary = primary if primary else primary_name(result)

    if mode == "internal":
        if not internal:
            raise ValueError("No hay un monitor interno conectado.")
        target = internal[0]
        for monitor in result:
            monitor.mirror = ""
            monitor.disabled = monitor.name != target.name
            if not monitor.disabled:
                monitor.x = 0
                monitor.y = 0
        _set_primary(result, target.name)
        return result

    if mode == "external":
        if not external:
            raise ValueError("No hay un monitor externo conectado.")
        target = external[0]
        for monitor in result:
            monitor.mirror = ""
            monitor.disabled = monitor.name != target.name
            if not monitor.disabled:
                monitor.x = 0
                monitor.y = 0
        _set_primary(result, target.name)
        return result

    if mode == "duplicate":
        target = next((m for m in result if m.name == current_primary), None)
        if target is None:
            target = (internal or result)[0]
        for monitor in result:
            monitor.disabled = False
            monitor.mirror = "" if monitor.name == target.name else target.name
            if monitor.name == target.name:
                monitor.x = 0
                monitor.y = 0
            else:
                monitor.x = target.x
                monitor.y = target.y
                monitor.scale = target.scale
                if any(
                    available.width == target.width and available.height == target.height
                    for available in monitor.available_modes
                ):
                    monitor.width = target.width
                    monitor.height = target.height
                    monitor.refresh = target.refresh
        _set_primary(result, target.name)
        return result

    if mode == "extend":
        target = next((m for m in result if m.name == current_primary), None)
        if target is None:
            target = (internal or result)[0]
        for monitor in result:
            monitor.disabled = False
            monitor.mirror = ""
        target.x = 0
        target.y = 0
        cursor_x = target.rect().right
        others = sorted(
            (monitor for monitor in result if monitor.name != target.name),
            key=lambda monitor: (monitor.x, monitor.name),
        )
        for monitor in others:
            monitor.x = cursor_x
            monitor.y = 0
            cursor_x += monitor.rect().w
        _set_primary(result, target.name)
        return result

    raise ValueError(f"Modo rápido desconocido: {mode}")


def detect_mode(monitors: Iterable[MonitorState]) -> str:
    active = enabled(monitors)
    if not active:
        return "extend"
    if len(active) == 1:
        return "internal" if active[0].is_internal else "external"
    if any(monitor.mirror for monitor in active):
        return "duplicate"
    return "extend"


def next_mode(mode: str) -> str:
    order = ["internal", "duplicate", "extend", "external"]
    try:
        return order[(order.index(mode) + 1) % len(order)]
    except ValueError:
        return "extend"


def rules_from_monitors(monitors: Iterable[MonitorState]) -> list[dict]:
    return [monitor.to_rule() for monitor in monitors]


def rule_key(rule: dict) -> tuple:
    return (
        str(rule.get("output", "")),
        str(rule.get("mode", "")),
        str(rule.get("position", "")),
        round(float(rule.get("scale", 1.0)), 3),
        int(rule.get("transform", 0)),
        str(rule.get("mirror", "") or ""),
        bool(rule.get("disabled", False)),
    )


def rules_equal(first: Iterable[dict], second: Iterable[dict]) -> bool:
    return sorted((rule_key(rule) for rule in first)) == sorted((rule_key(rule) for rule in second))


def parse_mode_string(value: str) -> tuple[int, int, float] | None:
    match = _MODE_STRING_RE.match(value.strip())
    if not match:
        return None
    width = int(match.group(1))
    height = int(match.group(2))
    refresh = float(match.group(3)) if match.group(3) else 60.0
    return width, height, refresh


def find_mode(modes: Iterable[Mode], width: int, height: int, refresh: float) -> Mode | None:
    candidates = [
        mode for mode in modes if mode.width == width and mode.height == height
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda mode: abs(mode.refresh - refresh))


def monitors_from_rules(
    monitors: Iterable[MonitorState],
    rules: Iterable[dict],
) -> list[MonitorState]:
    by_output = {str(rule.get("output", "")): rule for rule in rules}
    result: list[MonitorState] = []

    for monitor in monitors:
        updated = monitor.copy()
        rule = by_output.get(monitor.name)
        if rule is not None:
            updated.mirror = str(rule.get("mirror", "") or "")
            updated.disabled = bool(rule.get("disabled", False))
            raw_position = str(rule.get("position", "0x0"))
            match = re.match(r"^(-?\d+)x(-?\d+)$", raw_position)
            if match:
                updated.x = int(match.group(1))
                updated.y = int(match.group(2))
            updated.scale = float(rule.get("scale", 1.0))
            updated.transform = int(rule.get("transform", 0))

            raw_mode = str(rule.get("mode", "preferred"))
            if raw_mode and raw_mode != "preferred":
                parsed = parse_mode_string(raw_mode)
                if parsed is not None:
                    width, height, refresh = parsed
                    selected = find_mode(updated.available_modes, width, height, refresh)
                    if selected is not None:
                        updated.width = selected.width
                        updated.height = selected.height
                        updated.refresh = selected.refresh
                    else:
                        updated.width = width
                        updated.height = height
                        updated.refresh = refresh
        result.append(updated)

    return result
