"""Lógica compartida entre la interfaz gráfica y la CLI."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import config, hypr, layout, lua, profiles


@dataclass
class ApplyResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def load_profiles() -> profiles.ProfileStore:
    return profiles.ProfileStore()


def load_state() -> tuple[profiles.StateStore, profiles.State]:
    store = profiles.StateStore()
    return store, store.state


def current_monitors(primary: str | None = None) -> list[layout.MonitorState]:
    return layout.from_monitors(hypr.get_monitors(all_monitors=True), primary=primary)


def refresh_generated(profile_store: profiles.ProfileStore, state: profiles.State) -> Path:
    config.ensure_hypr_config_dir()
    path = config.generated_lua_path()
    config.atomic_write(path, lua.generate(profile_store.profiles, state))
    return path


def enable_persistence() -> tuple[bool, Path | None]:
    config.ensure_app_dir()
    return config.add_require_line()


def persistence_warning() -> str | None:
    if not config.hypr_lua_path().exists():
        return (
            f"No existe {config.hypr_lua_path()}: HyprDisplay solo soporta "
            "configuración Lua de Hyprland."
        )
    if not config.has_require_line():
        return (
            "La persistencia no está activada. Añade "
            f'{config.REQUIRE_LINE} a hyprland.lua o ejecuta "hyprdisplay doctor --fix".'
        )
    return None


def _restore_state(
    state: profiles.State,
    current_rules: list[dict],
    previous_rules: list[dict],
    active_profile: str,
    primary: str,
) -> None:
    state.current_rules = current_rules
    state.previous_rules = previous_rules
    state.active_profile = active_profile
    state.primary = primary


def pre_enable_rules(disabled_names: set[str], new_rules: list[dict]) -> list[dict]:
    """Reglas para activar primero, sin espejo, salidas desactivadas.

    Hyprland no crea el ``wl_output`` de un monitor que se habilita directamente
    en modo espejo. Como consecuencia, la barra, el fondo de pantalla y las
    capturas no ven esa salida ni siquiera después de quitar el espejo. Activar
    el monitor sin espejo un instante antes evita el problema.

    ``disabled_names`` son las salidas que ahora mismo están desactivadas según
    Hyprland (no el estado guardado, que puede estar desincronizado).
    """
    result: list[dict] = []
    for rule in new_rules:
        if rule.get("disabled") or not rule.get("mirror"):
            continue
        if rule.get("output") not in disabled_names:
            continue
        pre_rule = dict(rule)
        pre_rule["mirror"] = ""
        result.append(pre_rule)
    return result


def invisible_outputs(
    monitors: Iterable[layout.MonitorState] | None = None,
) -> list[str]:
    """Monitores activos y sin espejo que los clientes Wayland no ven."""
    monitors = list(monitors) if monitors is not None else current_monitors()
    visible = hypr.wayland_outputs()
    if visible is None:
        return []
    return [
        monitor.name
        for monitor in monitors
        if not monitor.disabled and not monitor.mirror and monitor.name not in visible
    ]


def repair_outputs(
    monitors: Iterable[layout.MonitorState] | None = None,
) -> list[str]:
    """Reinicializa las salidas que Hyprland no está exponiendo a las apps.

    Desactivar y volver a activar el monitor obliga a Hyprland a crear de nuevo
    su ``wl_output``. Devuelve los nombres reparados.
    """
    monitors = list(monitors) if monitors is not None else current_monitors()
    by_name = {monitor.name: monitor for monitor in monitors}
    repaired: list[str] = []
    for name in invisible_outputs(monitors):
        rule = by_name[name].to_rule()
        try:
            hypr.eval_lua(lua.rules_to_eval([dict(rule, disabled=True)]))
            time.sleep(0.5)
            hypr.eval_lua(lua.rules_to_eval([rule]))
        except hypr.HyprError:
            continue
        repaired.append(name)
    if repaired:
        time.sleep(0.4)
    return repaired


def apply_rules(
    rules: list[dict],
    profile_store: profiles.ProfileStore,
    state: profiles.State,
    *,
    persist: bool = True,
    add_require: bool = False,
    active_profile: str | None = None,
    primary: str | None = None,
) -> ApplyResult:
    old_rules = [dict(rule) for rule in state.current_rules]
    old_previous = [dict(rule) for rule in state.previous_rules]
    old_active = state.active_profile
    old_primary = state.primary
    old_file = config.read_text(config.generated_lua_path(), "")

    state.previous_rules = old_rules
    state.current_rules = [dict(rule) for rule in rules]
    state.active_profile = active_profile if active_profile is not None else old_active
    if primary is not None:
        state.primary = primary

    warnings: list[str] = []

    if persist:
        config.ensure_hypr_config_dir()
        if add_require and not config.has_require_line():
            try:
                config.add_require_line()
            except config.ConfigError as exc:
                warnings.append(str(exc))
        refresh_generated(profile_store, state)
        warning = persistence_warning()
        if warning:
            warnings.append(warning)

    # Solo consultamos Hyprland si hay alguna salida que se va a habilitar en
    # modo espejo: es el único caso en el que hace falta el pre-encendido.
    pre_rules: list[dict] = []
    if any(
        not rule.get("disabled") and rule.get("mirror")
        for rule in state.current_rules
    ):
        try:
            live = hypr.get_monitors(all_monitors=True)
        except hypr.HyprError:
            live = []
        disabled_names = {monitor.name for monitor in live if monitor.disabled}
        pre_rules = pre_enable_rules(disabled_names, state.current_rules)

    if pre_rules:
        try:
            hypr.eval_lua(lua.rules_to_eval(pre_rules))
            time.sleep(0.3)
        except hypr.HyprError:
            # El aplicado final es quien debe informar del error real.
            pass

    try:
        hypr.eval_lua(lua.rules_to_eval(state.current_rules))
    except hypr.HyprError as exc:
        _restore_state(state, old_rules, old_previous, old_active, old_primary)
        if persist:
            config.atomic_write(config.generated_lua_path(), old_file)
        return ApplyResult(False, [str(exc)])

    time.sleep(0.25)
    errors = hypr.get_config_errors()
    if errors:
        try:
            hypr.eval_lua(lua.rules_to_eval(old_rules))
        except hypr.HyprError:
            pass
        _restore_state(state, old_rules, old_previous, old_active, old_primary)
        if persist:
            config.atomic_write(config.generated_lua_path(), old_file)
        return ApplyResult(False, [f"Hyprland reportó errores de configuración:\n{errors}"])

    if persist:
        profiles.StateStore().save(state)

    return ApplyResult(True, warnings=warnings)


def apply_monitors(
    monitors: Iterable[layout.MonitorState],
    profile_store: profiles.ProfileStore,
    state: profiles.State,
    *,
    persist: bool = True,
    add_require: bool = False,
    active_profile: str | None = None,
    primary: str | None = None,
) -> ApplyResult:
    monitors = list(monitors)
    errors = layout.validate(monitors)
    if errors:
        return ApplyResult(False, errors=errors)

    result = apply_rules(
        layout.rules_from_monitors(monitors),
        profile_store,
        state,
        persist=persist,
        add_require=add_require,
        active_profile=active_profile,
        primary=primary,
    )
    result.warnings = layout.warnings(monitors) + result.warnings
    return result


def apply_profile(
    profile: profiles.Profile,
    monitors: Iterable[layout.MonitorState],
    profile_store: profiles.ProfileStore,
    state: profiles.State,
    *,
    persist: bool = True,
    add_require: bool = False,
) -> ApplyResult:
    monitors = list(monitors)
    updated = layout.monitors_from_rules(
        monitors,
        [entry.rule for entry in profile.monitors],
    )
    primary = profile.primary or layout.primary_name(updated)
    layout.ensure_primary(updated, primary)
    profile.last_used = int(time.time())
    profile_store.upsert(profile)
    result = apply_monitors(
        updated,
        profile_store,
        state,
        persist=persist,
        add_require=add_require,
        active_profile=profile.name,
        primary=primary,
    )
    if result.ok and persist:
        # Solo se guardan los perfiles cuando el cambio se aplicó bien; así una
        # aplicación fallida no puede sobrescribir profiles.json.
        profile_store.save()
    return result


def save_profile(
    name: str,
    monitors: Iterable[layout.MonitorState],
    profile_store: profiles.ProfileStore,
    state: profiles.State,
    *,
    auto: bool = True,
) -> profiles.Profile:
    monitors = list(monitors)
    primary = layout.primary_name(monitors)
    profile = profiles.Profile.from_monitors(name, monitors, primary=primary, auto=auto)
    profile_store.upsert(profile)
    profile_store.save()
    state.active_profile = name
    state.primary = primary
    profiles.StateStore().save(state)
    refresh_generated(profile_store, state)
    return profile


def apply_quick_mode(
    mode: str,
    monitors: Iterable[layout.MonitorState],
    profile_store: profiles.ProfileStore,
    state: profiles.State,
    *,
    persist: bool = True,
    add_require: bool = False,
) -> ApplyResult:
    monitors = list(monitors)
    updated = layout.quick_mode(mode, monitors, primary=state.primary)
    primary = layout.primary_name(updated)
    return apply_monitors(
        updated,
        profile_store,
        state,
        persist=persist,
        add_require=add_require,
        active_profile=None,
        primary=primary,
    )


def cycle_mode(
    monitors: Iterable[layout.MonitorState],
    profile_store: profiles.ProfileStore,
    state: profiles.State,
    *,
    persist: bool = True,
    add_require: bool = False,
) -> tuple[ApplyResult, str]:
    monitors = list(monitors)
    current = layout.detect_mode(monitors)
    target = layout.next_mode(current)
    return (
        apply_quick_mode(
            target,
            monitors,
            profile_store,
            state,
            persist=persist,
            add_require=add_require,
        ),
        target,
    )


def revert(
    profile_store: profiles.ProfileStore,
    state: profiles.State,
    *,
    persist: bool = True,
) -> ApplyResult:
    if not state.previous_rules:
        return ApplyResult(False, ["No hay una disposición anterior para revertir."])
    return apply_rules(
        state.previous_rules,
        profile_store,
        state,
        persist=persist,
        active_profile=None,
        primary=state.primary,
    )


def doctor() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []

    try:
        version = hypr.get_version()
        checks.append(("Hyprland", True, f"v{version.get('version', '?')}"))
        version_ok, version_detail = hypr.version_supported(version)
        checks.append(("Versión mínima", version_ok, version_detail))
    except hypr.HyprError as exc:
        checks.append(("Hyprland", False, str(exc)))
        return checks

    lua_ok = hypr.is_lua_config()
    checks.append(
        (
            "Configuración Lua",
            lua_ok,
            "Activa" if lua_ok else "No se detectó el parser Lua de Hyprland 0.55+",
        )
    )

    lua_path = config.hypr_lua_path()
    checks.append(
        (
            "hyprland.lua",
            lua_path.exists(),
            str(lua_path) if lua_path.exists() else f"No existe {lua_path}",
        )
    )

    has_require = config.has_require_line()
    checks.append(
        (
            "Línea require",
            has_require,
            config.REQUIRE_LINE if has_require else "Falta en hyprland.lua",
        )
    )

    generated = config.generated_lua_path()
    checks.append(
        (
            "Archivo generado",
            generated.exists(),
            str(generated) if generated.exists() else "Todavía no se ha generado",
        )
    )

    try:
        errors = hypr.get_config_errors()
        checks.append(
            (
                "Errores de configuración",
                not errors,
                errors if errors else "Sin errores",
            )
        )
    except hypr.HyprError as exc:
        checks.append(("Errores de configuración", False, str(exc)))

    try:
        profile_store = load_profiles()
        checks.append(
            (
                "Perfiles",
                True,
                f"{len(profile_store.profiles)} guardado(s) en {profile_store.path}",
            )
        )
    except config.ConfigError as exc:
        checks.append(("Perfiles", False, str(exc)))

    try:
        monitors = current_monitors()
        checks.append(
            (
                "Monitores",
                bool(monitors),
                ", ".join(monitor.name for monitor in monitors) or "Ninguno detectado",
            )
        )
    except hypr.HyprError as exc:
        checks.append(("Monitores", False, str(exc)))

    return checks
