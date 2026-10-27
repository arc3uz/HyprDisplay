"""Rutas y utilidades de configuración de HyprDisplay."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

APP_ID = "hyprdisplay"
APP_NAME = "HyprDisplay"
VERSION = "0.1.0"

REQUIRE_LINE = 'require("config.monitor-profiles")'


class ConfigError(RuntimeError):
    """Error de configuración o de escritura de archivos."""


def _xdg(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config")


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")


def app_dir() -> Path:
    return config_home() / APP_ID


def profiles_path() -> Path:
    return app_dir() / "profiles.json"


def state_path() -> Path:
    return app_dir() / "state.json"


def hypr_dir() -> Path:
    return config_home() / "hypr"


def hypr_lua_path() -> Path:
    return hypr_dir() / "hyprland.lua"


def binds_path() -> Path:
    return hypr_config_dir() / "binds.lua"


def hypr_config_dir() -> Path:
    return hypr_dir() / "config"


def generated_lua_path() -> Path:
    return hypr_config_dir() / "monitor-profiles.lua"


def ensure_app_dir() -> None:
    app_dir().mkdir(parents=True, exist_ok=True)


def ensure_hypr_config_dir() -> None:
    hypr_config_dir().mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, text: str) -> None:
    """Escribe un archivo de forma atómica en el mismo sistema de archivos."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-hyprdisplay")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    try:
        path.chmod(0o644)
    except OSError:
        pass


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-hyprdisplay-{stamp}")
    shutil.copy2(path, backup)
    return backup


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except OSError as exc:
        raise ConfigError(f"No se pudo leer {path}: {exc}") from exc


def has_require_line() -> bool:
    return REQUIRE_LINE in read_text(hypr_lua_path())


def add_require_line() -> tuple[bool, Path | None]:
    """Añade el require de HyprDisplay a hyprland.lua.

    Devuelve (cambiado, ruta_del_backup).
    """
    path = hypr_lua_path()
    if not path.exists():
        raise ConfigError(
            f"No existe {path}. HyprDisplay necesita una configuración Lua de Hyprland."
        )

    text = read_text(path)
    if REQUIRE_LINE in text:
        return False, None

    backup = backup_file(path)
    lines = text.splitlines()
    insert_at = len(lines)
    for index, line in enumerate(lines):
        if (
            'require("config.monitors")' in line
            or "require('config.monitors')" in line
        ):
            insert_at = index + 1
            break

    lines.insert(insert_at, REQUIRE_LINE)
    atomic_write(path, "\n".join(lines).rstrip("\n") + "\n")
    return True, backup


def _lua_quote(value: str) -> str:
    text = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{text}"'


def _match_paren(text: str, start: int) -> int:
    """Devuelve el índice del paréntesis de cierre que equilibra text[start]."""
    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _key_matches(first_arg: str, key: str) -> bool:
    compact = "".join(first_arg.split())
    key_compact = "".join(key.split())
    if key_compact in compact:
        return True
    final_key = key_compact.rsplit("+", 1)[-1]
    return compact.endswith(f'"+{final_key}"')


def install_shortcut(
    key: str = "SUPER + P",
    command: str = "hyprdisplay gui",
) -> tuple[str, Path | None]:
    """Instala o actualiza el atajo en binds.lua.

    Devuelve (estado, backup). Los estados son "added", "replaced" o "present".
    """
    path = binds_path()
    if not path.exists():
        raise ConfigError(
            f"No existe {path}. HyprDisplay espera una configuración Lua de Hyprland."
        )

    text = read_text(path)
    replacement = (
        f"hl.bind({_lua_quote(key)},\n"
        f"    hl.dsp.exec_cmd({_lua_quote(command)}))"
    )

    cursor = 0
    while True:
        start = text.find("hl.bind(", cursor)
        if start == -1:
            break
        end = _match_paren(text, start + len("hl.bind"))
        if end == -1:
            break

        block = text[start:end + 1]
        first_arg = block[len("hl.bind("):].split(",", 1)[0].strip()
        if _key_matches(first_arg, key):
            if command in block:
                return "present", None
            backup = backup_file(path)
            atomic_write(path, text[:start] + replacement + text[end + 1:])
            return "replaced", backup

        cursor = end + 1

    backup = backup_file(path)
    addition = (
        "\n-- Atajo de HyprDisplay\n"
        f"hl.bind({_lua_quote(key)},\n"
        f"    hl.dsp.exec_cmd({_lua_quote(command)}))\n"
    )
    atomic_write(path, text.rstrip("\n") + "\n" + addition)
    return "added", backup
