"""Interfaz de línea de comandos de HyprDisplay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, core, hypr, layout, profiles


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hyprdisplay",
        description="Configura la disposición de monitores en Hyprland.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="Abre la interfaz gráfica.")

    list_parser = sub.add_parser("list", help="Lista los perfiles guardados.")
    list_parser.add_argument("--json", action="store_true", help="Salida JSON.")

    status_parser = sub.add_parser("status", help="Muestra los monitores y el modo actual.")
    status_parser.add_argument("-j", "--json", action="store_true", help="Salida JSON.")

    apply_parser = sub.add_parser("apply", help="Aplica un perfil guardado.")
    apply_parser.add_argument("name")
    apply_parser.add_argument("--no-persist", action="store_true", help="No escribe la configuración.")
    apply_parser.add_argument("--fix-config", action="store_true", help="Añade el require si falta.")

    save_parser = sub.add_parser("save", help="Guarda la disposición actual como perfil.")
    save_parser.add_argument("name")
    save_parser.add_argument("--no-auto", action="store_true", help="No aplicar al conectar monitores.")

    delete_parser = sub.add_parser("delete", help="Elimina un perfil.")
    delete_parser.add_argument("name")

    mode_parser = sub.add_parser("mode", help="Aplica un modo rápido tipo Win+P.")
    mode_parser.add_argument("mode", choices=list(layout.QUICK_MODES))
    mode_parser.add_argument("--no-persist", action="store_true", help="No escribe la configuración.")
    mode_parser.add_argument("--fix-config", action="store_true", help="Añade el require si falta.")

    cycle_parser = sub.add_parser("cycle", help="Pasa al siguiente modo rápido.")
    cycle_parser.add_argument("--no-persist", action="store_true", help="No escribe la configuración.")
    cycle_parser.add_argument("--fix-config", action="store_true", help="Añade el require si falta.")

    revert_parser = sub.add_parser("revert", help="Vuelve a la disposición anterior.")
    revert_parser.add_argument("--no-persist", action="store_true", help="No escribe la configuración.")

    doctor_parser = sub.add_parser("doctor", help="Comprueba el estado de la instalación.")
    doctor_parser.add_argument("--fix", action="store_true", help="Añade el require y regenera el Lua.")

    sub.add_parser(
        "repair",
        help="Reinicializa salidas que las apps no ven (sin barra ni fondo).",
    )

    shortcut_parser = sub.add_parser(
        "shortcut",
        help="Instala o actualiza el atajo de teclado en binds.lua.",
    )
    shortcut_parser.add_argument("--key", default="SUPER + P", help="Combinación de teclas.")
    shortcut_parser.add_argument(
        "--exec",
        dest="exec_command",
        default="hyprdisplay gui",
        help="Comando que ejecuta el atajo.",
    )
    shortcut_parser.add_argument(
        "--reload",
        action="store_true",
        help="Recarga Hyprland al terminar.",
    )

    export_parser = sub.add_parser("export", help="Exporta los perfiles a un archivo JSON.")
    export_parser.add_argument("path", type=Path)

    import_parser = sub.add_parser("import", help="Importa perfiles desde un archivo JSON.")
    import_parser.add_argument("path", type=Path)

    return parser


def _print_result(result: core.ApplyResult) -> int:
    if result.ok:
        print("OK")
    else:
        for error in result.errors:
            print(f"Error: {error}", file=sys.stderr)
    for warning in result.warnings:
        print(f"Aviso: {warning}", file=sys.stderr)
    for message in result.messages:
        print(message)
    return 0 if result.ok else 1


def _monitors_for_state(state) -> list[layout.MonitorState]:
    return core.current_monitors(primary=state.primary)


def cmd_list(args: argparse.Namespace) -> int:
    store = core.load_profiles()
    _, state = core.load_state()
    if args.json:
        print(
            json.dumps(
                {
                    "active": state.active_profile,
                    "profiles": [profile.to_dict() for profile in store.profiles],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not store.profiles:
        print("No hay perfiles guardados.")
        return 0

    for profile in store.profiles:
        marker = "*" if profile.name == state.active_profile else " "
        auto = "auto" if profile.auto else "manual"
        print(f"{marker} {profile.name}  ({len(profile.monitors)} monitores, {auto})")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = core.load_profiles()
    _, state = core.load_state()
    monitors = _monitors_for_state(state)
    mode = layout.detect_mode(monitors)
    primary = layout.primary_name(monitors)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": mode,
                    "primary": primary,
                    "active_profile": state.active_profile,
                    "monitors": [
                        {
                            "name": monitor.name,
                            "description": monitor.description,
                            "serial": monitor.serial,
                            "fingerprint": monitor.fingerprint,
                            "width": monitor.width,
                            "height": monitor.height,
                            "refresh": monitor.refresh,
                            "scale": monitor.scale,
                            "transform": monitor.transform,
                            "position": [monitor.x, monitor.y],
                            "mirror": monitor.mirror,
                            "disabled": monitor.disabled,
                            "primary": monitor.primary,
                        }
                        for monitor in monitors
                    ],
                    "profiles": store.names(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"Modo actual: {layout.QUICK_MODE_LABELS.get(mode, mode)}")
    print(f"Perfil activo: {state.active_profile or 'ninguno'}")
    print(f"Primario: {primary or 'ninguno'}")
    print()
    for monitor in monitors:
        state_label = "desactivado" if monitor.disabled else "activo"
        mirror = f", espejo de {monitor.mirror}" if monitor.mirror else ""
        print(
            f"- {monitor.name}: {monitor.width}x{monitor.height}@{monitor.refresh:g} "
            f"escala {monitor.scale:g}, posición {monitor.x}x{monitor.y}, "
            f"rotación {monitor.transform * 90}°, {state_label}{mirror}"
        )
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    store = core.load_profiles()
    _, state = core.load_state()
    profile = store.get(args.name)
    if profile is None:
        print(f"Error: no existe el perfil «{args.name}».", file=sys.stderr)
        return 1
    monitors = _monitors_for_state(state)
    result = core.apply_profile(
        profile,
        monitors,
        store,
        state,
        persist=not args.no_persist,
        add_require=args.fix_config,
    )
    return _print_result(result)


def cmd_save(args: argparse.Namespace) -> int:
    store = core.load_profiles()
    _, state = core.load_state()
    monitors = _monitors_for_state(state)
    profile = core.save_profile(
        args.name,
        monitors,
        store,
        state,
        auto=not args.no_auto,
    )
    print(f"Perfil «{profile.name}» guardado con {len(profile.monitors)} monitor(es).")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    store = core.load_profiles()
    if not store.delete(args.name):
        print(f"Error: no existe el perfil «{args.name}».", file=sys.stderr)
        return 1
    store.save()
    _, state = core.load_state()
    if state.active_profile == args.name:
        state.active_profile = ""
        profiles.StateStore().save(state)
    core.refresh_generated(store, state)
    print(f"Perfil «{args.name}» eliminado.")
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    store = core.load_profiles()
    _, state = core.load_state()
    monitors = _monitors_for_state(state)
    result = core.apply_quick_mode(
        args.mode,
        monitors,
        store,
        state,
        persist=not args.no_persist,
        add_require=args.fix_config,
    )
    return _print_result(result)


def cmd_cycle(args: argparse.Namespace) -> int:
    store = core.load_profiles()
    _, state = core.load_state()
    monitors = _monitors_for_state(state)
    result, target = core.cycle_mode(
        monitors,
        store,
        state,
        persist=not args.no_persist,
        add_require=args.fix_config,
    )
    if result.ok:
        print(f"Modo aplicado: {layout.QUICK_MODE_LABELS.get(target, target)}")
    return _print_result(result)


def cmd_revert(args: argparse.Namespace) -> int:
    store = core.load_profiles()
    _, state = core.load_state()
    result = core.revert(store, state, persist=not args.no_persist)
    return _print_result(result)


def cmd_doctor(args: argparse.Namespace) -> int:
    if args.fix:
        try:
            changed, backup = core.enable_persistence()
            if changed:
                print(f"Línea require añadida a {config.hypr_lua_path()}.")
                if backup:
                    print(f"Copia de seguridad: {backup}")
            else:
                print("La línea require ya estaba presente.")
            store = core.load_profiles()
            _, state = core.load_state()
            path = core.refresh_generated(store, state)
            print(f"Configuración generada en {path}.")
        except config.ConfigError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    checks = core.doctor()
    failed = False
    for label, ok, detail in checks:
        marker = "OK  " if ok else "FAIL"
        print(f"[{marker}] {label}: {detail}")
        if not ok:
            failed = True
    return 1 if failed else 0


def cmd_repair(args: argparse.Namespace) -> int:
    try:
        monitors = core.current_monitors()
    except hypr.HyprError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    missing = core.invisible_outputs(monitors)
    if missing == [] and hypr.wayland_outputs() is None:
        print(
            "No se pudo consultar las salidas Wayland (GDK no disponible o sin "
            "sesión gráfica).",
            file=sys.stderr,
        )
        return 1
    if not missing:
        print("Todas las salidas activas son visibles para las aplicaciones.")
        return 0

    print("Salidas no visibles: " + ", ".join(missing))
    repaired = core.repair_outputs(monitors)
    if repaired:
        print("Reparadas: " + ", ".join(repaired))
    failed = [name for name in missing if name not in repaired]
    if failed:
        print("No se pudieron reparar: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


def cmd_shortcut(args: argparse.Namespace) -> int:
    try:
        status, backup = config.install_shortcut(args.key, args.exec_command)
    except config.ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    messages = {
        "added": f"Atajo {args.key} añadido a {config.binds_path()}.",
        "replaced": f"Atajo {args.key} actualizado en {config.binds_path()}.",
        "present": f"El atajo {args.key} ya estaba configurado.",
    }
    print(messages.get(status, status))
    if backup is not None:
        print(f"Copia de seguridad: {backup}")

    if args.reload:
        try:
            hypr.reload_config()
            print("Hyprland recargado.")
        except hypr.HyprError as exc:
            print(f"Aviso: no se pudo recargar Hyprland: {exc}", file=sys.stderr)
            return 1
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    store = core.load_profiles()
    store.export_to(args.path)
    print(f"Perfiles exportados a {args.path}.")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    store = core.load_profiles()
    count = store.import_from(args.path)
    print(f"{count} perfil(es) importados.")
    return 0


def launch_gui() -> int:
    try:
        from .app import main as gui_main
    except Exception as exc:  # pragma: no cover - depende del entorno gráfico
        print(f"No se pudo cargar la interfaz GTK4: {exc}", file=sys.stderr)
        return 1
    return gui_main()


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.command is None or args.command == "gui":
        return launch_gui()

    try:
        handlers = {
            "list": cmd_list,
            "status": cmd_status,
            "apply": cmd_apply,
            "save": cmd_save,
            "delete": cmd_delete,
            "mode": cmd_mode,
            "cycle": cmd_cycle,
            "revert": cmd_revert,
            "doctor": cmd_doctor,
            "repair": cmd_repair,
            "shortcut": cmd_shortcut,
            "export": cmd_export,
            "import": cmd_import,
        }
        return handlers[args.command](args)
    except (config.ConfigError, hypr.HyprError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
