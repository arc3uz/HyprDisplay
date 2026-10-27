"""Capa de comunicación con Hyprland mediante hyprctl."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any


class HyprError(RuntimeError):
    """Error al ejecutar hyprctl o al interpretar su salida."""


_MODE_RE = re.compile(r"^(\d+)x(\d+)@([0-9.]+)Hz$")
_POS_RE = re.compile(r"^(-?\d+)x(-?\d+)$")
_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)")

#: Primera versión de Hyprland con config manager Lua estable.
MIN_VERSION = (0, 55)


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    refresh: float

    @property
    def label(self) -> str:
        return f"{self.width}×{self.height} @ {self.refresh:g} Hz"

    @property
    def mode_string(self) -> str:
        return f"{self.width}x{self.height}@{self.refresh:g}"

    @classmethod
    def parse(cls, value: str) -> "Mode | None":
        match = _MODE_RE.match(value.strip())
        if not match:
            return None
        return cls(int(match.group(1)), int(match.group(2)), float(match.group(3)))


@dataclass
class Monitor:
    name: str
    description: str
    make: str
    model: str
    serial: str
    width: int
    height: int
    physical_width: int
    physical_height: int
    refresh_rate: float
    x: int
    y: int
    scale: float
    transform: int
    disabled: bool
    mirror_of: str
    focused: bool
    vrr: bool
    available_modes: list[Mode] = field(default_factory=list)
    active_workspace: int = 0

    @property
    def fingerprint(self) -> str:
        return f"{self.description}|{self.serial}"

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Monitor":
        modes: list[Mode] = []
        for raw in data.get("availableModes") or []:
            mode = Mode.parse(str(raw))
            if mode is not None:
                modes.append(mode)

        width = int(data.get("width") or 0)
        height = int(data.get("height") or 0)
        refresh = float(data.get("refreshRate") or 0.0)

        if not modes and width > 0 and height > 0:
            modes = [Mode(width, height, refresh or 60.0)]

        if (width <= 0 or height <= 0) and modes:
            width, height = modes[0].width, modes[0].height
        if refresh <= 0 and modes:
            refresh = modes[0].refresh

        workspace = data.get("activeWorkspace") or {}
        return cls(
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            make=str(data.get("make") or ""),
            model=str(data.get("model") or ""),
            serial=str(data.get("serial") or ""),
            width=width,
            height=height,
            physical_width=int(data.get("physicalWidth") or 0),
            physical_height=int(data.get("physicalHeight") or 0),
            refresh_rate=refresh,
            x=int(data.get("x") or 0),
            y=int(data.get("y") or 0),
            scale=float(data.get("scale") or 1.0),
            transform=int(data.get("transform") or 0),
            disabled=bool(data.get("disabled") or False),
            mirror_of=str(data.get("mirrorOf") or "none"),
            focused=bool(data.get("focused") or False),
            vrr=bool(data.get("vrr") or False),
            available_modes=modes,
            active_workspace=int(workspace.get("id") or 0),
        )


def _env() -> dict[str, str]:
    env = os.environ.copy()
    if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return env

    # uwsm exporta la variable al entorno de systemd, pero si se ejecuta desde
    # un servicio sin ella intentamos descubrir la instancia.
    try:
        result = subprocess.run(
            ["hyprctl", "instances", "-j"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
        if result.returncode == 0:
            instances = json.loads(result.stdout or "[]")
            if instances:
                env["HYPRLAND_INSTANCE_SIGNATURE"] = instances[0]["instance"]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, IndexError):
        pass
    return env


def _run(args: list[str], timeout: int = 15) -> str:
    try:
        result = subprocess.run(
            ["hyprctl", *args],
            capture_output=True,
            text=True,
            env=_env(),
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise HyprError("hyprctl no está instalado o no está en PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise HyprError("hyprctl tardó demasiado en responder.") from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        raise HyprError(stderr or stdout or f"hyprctl terminó con código {result.returncode}.")

    if stdout.startswith("error:"):
        raise HyprError(stdout)

    return stdout


def _run_json(args: list[str]) -> Any:
    output = _run(args)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise HyprError(f"Respuesta JSON inválida de hyprctl: {exc}") from exc


def get_version() -> dict[str, Any]:
    return _run_json(["-j", "version"])


def parse_version(text: object) -> tuple[int, ...]:
    """Convierte ``"0.56.2"`` o ``"v0.56.2"`` en una tupla comparable.

    Devuelve una tupla vacía si el texto no empieza por un número de versión.
    """
    match = _VERSION_RE.match(str(text or "").strip())
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def version_supported(version: dict[str, Any]) -> tuple[bool, str]:
    """Comprueba que la versión de Hyprland soporte el config manager Lua.

    Devuelve ``(soportada, detalle)`` listo para mostrar en ``doctor``.
    """
    raw = str(version.get("version") or version.get("tag") or "").strip()
    label = raw or "desconocida"
    parsed = parse_version(raw)

    if not parsed:
        return False, f"{label} (no se pudo interpretar; se requiere 0.55+)"
    if parsed < MIN_VERSION:
        return False, f"{label} (se requiere 0.55+)"
    return True, f"{label} ≥ 0.55"


def resolve_mirror_names(monitors: list[Monitor], data: list[Any]) -> None:
    """Traduce el id numérico de ``mirrorOf`` al nombre del monitor.

    Hyprland puede devolver ``"mirrorOf": "0"`` (el id) en lugar del nombre del
    monitor espejado. Sin esta traducción, las reglas generarían ``mirror = "0"``
    y Hyprland las rechazaría.
    """
    by_id = {
        int(item.get("id", -1)): str(item.get("name") or "")
        for item in data
        if isinstance(item, dict) and item.get("name") is not None
    }
    for monitor in monitors:
        value = monitor.mirror_of.strip()
        if value in ("", "none"):
            monitor.mirror_of = ""
            continue
        if value.isdigit():
            monitor.mirror_of = by_id.get(int(value), "")


def get_monitors(all_monitors: bool = True) -> list[Monitor]:
    args = ["-j", "monitors"]
    if all_monitors:
        args.append("all")
    data = _run_json(args)
    if not isinstance(data, list):
        raise HyprError("hyprctl no devolvió una lista de monitores.")
    monitors = [Monitor.from_json(item) for item in data if isinstance(item, dict)]
    resolve_mirror_names(monitors, data)
    return monitors


def wayland_outputs() -> set[str] | None:
    """Salidas que los clientes Wayland pueden ver, según GDK.

    Hyprland puede dejar un monitor habilitado sin su objeto ``wl_output``; en
    ese caso la barra, el fondo de pantalla o las capturas no lo ven. Devuelve
    ``None`` si no se puede consultar (sin GDK o sin sesión gráfica).
    """
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        return None

    try:
        import gi

        gi.require_version("Gdk", "4.0")
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gdk, Gtk
    except (ImportError, ValueError):
        return None

    try:
        if Gdk.Display.get_default() is None:
            Gtk.init_check()
        display = Gdk.Display.get_default()
        if display is None:
            return None
        monitors = display.get_monitors()
        names: set[str] = set()
        for index in range(monitors.get_n_items()):
            connector = monitors.get_item(index).get_connector()
            if connector:
                names.add(connector)
    except Exception:  # noqa: BLE001 - sin sesión gráfica disponible
        return None

    return names


def get_config_errors() -> str:
    return _run(["configerrors"]).strip()


def eval_lua(code: str) -> str:
    """Ejecuta código Lua en el config manager de Hyprland."""
    # hyprctl interpreta un argumento que empieza por "-" como una opción; los
    # archivos generados empiezan por un comentario "--".
    if code.startswith("-"):
        code = "\n" + code
    return _run(["eval", code], timeout=20)


def is_lua_config() -> bool:
    try:
        eval_lua('if hl == nil then error("hyprdisplay: no lua config") end')
        return True
    except HyprError:
        return False


def reload_config() -> str:
    return _run(["reload"])


def notify(message: str, timeout_ms: int = 5000) -> None:
    try:
        _run(["notify", "1", str(timeout_ms), "rgb(89cff0)", message])
    except HyprError:
        pass


def parse_position(value: str) -> tuple[int, int] | None:
    match = _POS_RE.match(value.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))
