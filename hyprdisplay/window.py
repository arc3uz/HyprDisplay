"""Ventana principal de HyprDisplay."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, GObject, Gtk  # noqa: E402

from . import config, core, hypr, layout, profiles  # noqa: E402
from .canvas import MonitorCanvas  # noqa: E402


def _signature(monitors: list[layout.MonitorState]) -> tuple:
    return tuple(
        sorted(
            (
                monitor.name,
                monitor.disabled,
                monitor.width,
                monitor.height,
                round(monitor.refresh, 2),
                round(monitor.scale, 3),
                monitor.x,
                monitor.y,
                monitor.transform,
                monitor.mirror,
            )
            for monitor in monitors
        )
    )


def _resolution_options(monitor: layout.MonitorState) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for mode in sorted(
        monitor.available_modes,
        key=lambda item: (item.width * item.height, item.width, item.height),
        reverse=True,
    ):
        key = (mode.width, mode.height)
        if key not in seen:
            seen.add(key)
            pairs.append(key)
    if (monitor.width, monitor.height) not in seen:
        pairs.insert(0, (monitor.width, monitor.height))
    return pairs


def _refresh_options(monitor: layout.MonitorState) -> list[float]:
    values = sorted(
        {
            round(mode.refresh, 2)
            for mode in monitor.available_modes
            if mode.width == monitor.width and mode.height == monitor.height
        },
        reverse=True,
    )
    if not values:
        values = [round(monitor.refresh, 2)]
    current = round(monitor.refresh, 2)
    if current not in values:
        values.append(current)
        values.sort(reverse=True)
    return values


def _scale_options(monitor: layout.MonitorState) -> list[float]:
    values = layout.valid_scales(monitor.width, monitor.height)
    if not values:
        values = [monitor.scale]
    if not any(abs(value - monitor.scale) < 1e-6 for value in values):
        values.append(monitor.scale)
        values.sort()
    return values


def _index_of_float(values: list[float], value: float) -> int:
    for index, candidate in enumerate(values):
        if abs(candidate - value) < 1e-6:
            return index
    return 0


class MainWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        application: Adw.Application,
        store: profiles.ProfileStore,
        state_store: profiles.StateStore,
        state: profiles.State,
    ) -> None:
        super().__init__(application=application, title="HyprDisplay")
        self.set_default_size(1180, 760)
        self.set_size_request(720, 480)

        self.store = store
        self.state_store = state_store
        self.state = state

        self.monitors: list[layout.MonitorState] = []
        self.snapshot: list[layout.MonitorState] = []
        self.position_rows: dict[str, Adw.ActionRow] = {}
        self._groups: list[Adw.PreferencesGroup] = []
        self.dirty = False
        self._updating = False
        self._selected_profile_name = state.active_profile
        self._last_signature: tuple | None = None
        self._pending_notified = False

        self._build_ui()
        self._install_actions()
        self._load_profiles_into_dropdown(selected=state.active_profile or None)
        self._refresh_monitors(initial=True)
        self._check_persistence()
        GLib.idle_add(self._check_outputs)
        GLib.timeout_add_seconds(3, self._poll_monitors)

    # --------------------------------------------------------------- UI base

    def _build_ui(self) -> None:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        self.menu = Gio.Menu()
        self.menu.append("Guardar perfil actual", "win.save-profile")
        self.menu.append("Gestionar perfiles", "win.manage-profiles")
        self.menu.append("Exportar perfiles…", "win.export-profiles")
        self.menu.append("Importar perfiles…", "win.import-profiles")
        self.menu.append("Diagnóstico", "win.doctor")
        self.menu.append("Abrir configuración", "win.open-config")
        self.menu.append("Acerca de HyprDisplay", "win.about")

        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(self.menu)
        menu_button.set_tooltip_text("Menú")
        header.pack_end(menu_button)

        self.sidebar_button = Gtk.ToggleButton(icon_name="sidebar-show-symbolic")
        self.sidebar_button.set_tooltip_text("Mostrar u ocultar el panel de ajustes")
        header.pack_start(self.sidebar_button)

        identify_button = Gtk.Button(label="Identificar")
        identify_button.connect("clicked", lambda _button: self.canvas.identify())
        header.pack_start(identify_button)

        refresh_button = Gtk.Button(label="Actualizar")
        refresh_button.connect("clicked", lambda _button: self._refresh_monitors(force=True))
        header.pack_start(refresh_button)

        self.toast_overlay = Adw.ToastOverlay()

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.banner = Adw.Banner(
            title="La persistencia no está activada.",
            button_label="Activar",
        )
        self.banner.connect("button-clicked", lambda _banner: self._on_enable_persistence())
        self.banner.set_revealed(False)
        content.append(self.banner)

        # FlowBox en lugar de una fila fija: en ventanas estrechas los botones
        # pasan a una segunda línea en vez de quedar cortados.
        top = Gtk.FlowBox()
        top.set_selection_mode(Gtk.SelectionMode.NONE)
        top.set_homogeneous(False)
        top.set_column_spacing(8)
        top.set_row_spacing(8)
        top.set_max_children_per_line(20)
        top.set_min_children_per_line(1)
        top.set_valign(Gtk.Align.START)
        top.set_margin_top(8)
        top.set_margin_bottom(8)
        top.set_margin_start(12)
        top.set_margin_end(12)

        top.append(Gtk.Label(label="Perfil:"))
        self.profile_dropdown = Gtk.DropDown(model=Gtk.StringList.new(["Sin perfil"]))
        self.profile_dropdown.set_tooltip_text("Cargar un perfil guardado")
        self.profile_dropdown.connect("notify::selected", self._on_profile_selected)
        top.append(self.profile_dropdown)

        for mode in layout.QUICK_MODES:
            button = Gtk.Button(label=layout.QUICK_MODE_LABELS[mode])
            button.set_tooltip_text(f"Aplicar «{layout.QUICK_MODE_LABELS[mode]}»")
            button.connect("clicked", lambda _button, value=mode: self._on_quick_mode(value))
            top.append(button)

        content.append(top)

        self.canvas = MonitorCanvas()
        self.canvas.on_change = self._on_canvas_change
        self.canvas.set_hexpand(True)
        self.canvas.set_vexpand(True)

        canvas_frame = Gtk.Frame()
        canvas_frame.set_child(self.canvas)
        canvas_frame.set_hexpand(True)
        canvas_frame.set_vexpand(True)
        canvas_frame.set_margin_start(12)
        canvas_frame.set_margin_end(6)
        canvas_frame.set_margin_bottom(8)

        self.prefs_page = Adw.PreferencesPage()
        self.prefs_page.set_hexpand(True)
        self.prefs_page.set_vexpand(True)

        sidebar = Gtk.ScrolledWindow()
        sidebar.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar.set_child(self.prefs_page)
        sidebar.set_margin_end(6)
        sidebar.set_margin_bottom(8)

        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_sidebar_position(Gtk.PackType.END)
        self.split_view.set_sidebar(sidebar)
        self.split_view.set_content(canvas_frame)
        self.split_view.set_show_sidebar(True)
        self.split_view.set_min_sidebar_width(340)
        self.split_view.set_max_sidebar_width(430)
        self.split_view.set_sidebar_width_fraction(0.32)
        self.split_view.set_pin_sidebar(False)
        self.split_view.set_vexpand(True)
        content.append(self.split_view)

        self.sidebar_button.set_active(True)
        self.sidebar_button.bind_property(
            "active",
            self.split_view,
            "show-sidebar",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )

        breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 1000px")
        )
        breakpoint.add_setter(self.split_view, "collapsed", True)
        breakpoint.add_setter(self.split_view, "show-sidebar", False)
        self.add_breakpoint(breakpoint)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bottom.set_margin_start(12)
        bottom.set_margin_end(12)
        bottom.set_margin_bottom(10)
        bottom.set_margin_top(2)

        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0)
        self.status_label.set_hexpand(True)
        self.status_label.add_css_class("dim-label")
        bottom.append(self.status_label)

        self.revert_button = Gtk.Button(label="Revertir")
        self.revert_button.set_tooltip_text("Volver a la disposición anterior")
        self.revert_button.connect("clicked", lambda _button: self._revert())
        bottom.append(self.revert_button)

        self.apply_button = Gtk.Button(label="Aplicar")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.set_tooltip_text("Aplicar y guardar la disposición")
        self.apply_button.connect("clicked", lambda _button: self._apply())
        bottom.append(self.apply_button)

        content.append(bottom)
        self.toast_overlay.set_child(content)
        toolbar.set_content(self.toast_overlay)
        self.set_content(toolbar)

    def _install_actions(self) -> None:
        actions = {
            "apply": lambda: self._apply(),
            "revert": lambda: self._revert(),
            "refresh": lambda: self._refresh_monitors(force=True),
            "identify": lambda: self.canvas.identify(),
            "save-profile": lambda: self._on_save_profile(),
            "manage-profiles": lambda: self._manage_profiles(),
            "export-profiles": lambda: self._on_export(),
            "import-profiles": lambda: self._on_import(),
            "doctor": lambda: self._doctor(),
            "open-config": lambda: self._open_config(),
            "about": lambda: self._on_about(),
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _action, _param, cb=callback: cb())
            self.add_action(action)

    # ------------------------------------------------------------- data load

    def _refresh_monitors(self, force: bool = False, initial: bool = False) -> None:
        try:
            monitors = core.current_monitors(primary=self.state.primary)
        except hypr.HyprError as exc:
            self._toast(f"No se pudieron leer los monitores: {exc}")
            return

        signature = _signature(monitors)
        if not force and not initial and self.dirty and signature != self._last_signature:
            self._toast("Los monitores cambiaron. Aplica o descarta los cambios antes de actualizar.")
            return

        primary = self.state.primary or layout.primary_name(monitors)
        layout.ensure_primary(monitors, primary)
        self.state.primary = layout.primary_name(monitors)
        self.monitors = monitors
        self._last_signature = signature
        self.dirty = False

        if initial:
            self.snapshot = [monitor.copy() for monitor in monitors]
            if self.state.active_profile:
                self._selected_profile_name = self.state.active_profile

        self._update_canvas()
        self._rebuild_sidebar()
        self._update_status()

    def _poll_monitors(self) -> bool:
        if not self.get_visible():
            return True
        try:
            monitors = core.current_monitors(primary=self.state.primary)
        except hypr.HyprError:
            return True

        signature = _signature(monitors)
        if signature == self._last_signature:
            self._pending_notified = False
            return True

        if not self.dirty:
            self._refresh_monitors(force=True)
            self._toast("Monitores actualizados.")
        elif not self._pending_notified:
            self._pending_notified = True
            self._toast("Monitores cambiados. Pulsa Actualizar para recargar.")
        return True

    # ------------------------------------------------------------- sidebar

    def _rebuild_sidebar(self) -> None:
        self._updating = True
        for group in self._groups:
            self.prefs_page.remove(group)
        self._groups.clear()
        self.position_rows = {}

        primary = layout.primary_name(self.monitors)

        for monitor in self.monitors:
            title = monitor.name
            if monitor.description:
                title += f" · {monitor.description}"
            group = Adw.PreferencesGroup(title=title)
            self.prefs_page.add(group)
            self._groups.append(group)

            active_row = Adw.SwitchRow(
                title="Activo",
                subtitle="Incluir este monitor en la disposición",
            )
            active_row.set_active(not monitor.disabled)
            active_row.connect(
                "notify::active",
                lambda row, _param, name=monitor.name: self._on_active_toggled(name, row.get_active()),
            )
            group.add(active_row)

            resolutions = _resolution_options(monitor)
            resolution_row = Adw.ComboRow(title="Resolución")
            resolution_row.set_model(
                Gtk.StringList.new([f"{width} × {height}" for width, height in resolutions])
            )
            current_resolution = (monitor.width, monitor.height)
            resolution_row.set_selected(
                resolutions.index(current_resolution) if current_resolution in resolutions else 0
            )
            resolution_row.connect(
                "notify::selected",
                lambda row, _param, name=monitor.name: self._on_resolution_changed(name, row.get_selected()),
            )
            group.add(resolution_row)

            refreshes = _refresh_options(monitor)
            refresh_row = Adw.ComboRow(title="Frecuencia")
            refresh_row.set_model(Gtk.StringList.new([f"{value:g} Hz" for value in refreshes]))
            refresh_row.set_selected(_index_of_float(refreshes, monitor.refresh))
            refresh_row.connect(
                "notify::selected",
                lambda row, _param, name=monitor.name: self._on_refresh_changed(name, row.get_selected()),
            )
            group.add(refresh_row)

            scales = _scale_options(monitor)
            scale_row = Adw.ComboRow(title="Escala")
            scale_row.set_model(Gtk.StringList.new([f"{round(value * 100):g} %" for value in scales]))
            scale_row.set_selected(_index_of_float(scales, monitor.scale))
            scale_row.connect(
                "notify::selected",
                lambda row, _param, name=monitor.name: self._on_scale_changed(name, row.get_selected()),
            )
            group.add(scale_row)

            rotation_row = Adw.ComboRow(title="Rotación")
            rotation_row.set_model(Gtk.StringList.new(["0°", "90°", "180°", "270°"]))
            rotation_row.set_selected(monitor.transform if monitor.transform in (0, 1, 2, 3) else 0)
            rotation_row.connect(
                "notify::selected",
                lambda row, _param, name=monitor.name: self._on_rotation_changed(name, row.get_selected()),
            )
            group.add(rotation_row)

            mirror_options = [""] + [
                other.name
                for other in self.monitors
                if other.name != monitor.name and not other.disabled
            ]
            if monitor.mirror and monitor.mirror not in mirror_options:
                mirror_options.append(monitor.mirror)
            mirror_row = Adw.ComboRow(title="Espejo de")
            mirror_row.set_model(
                Gtk.StringList.new(
                    ["Ninguno"] + [name for name in mirror_options[1:]]
                )
            )
            mirror_row.set_selected(
                mirror_options.index(monitor.mirror) if monitor.mirror in mirror_options else 0
            )
            mirror_row.connect(
                "notify::selected",
                lambda row, _param, name=monitor.name: self._on_mirror_changed(name, row.get_selected()),
            )
            group.add(mirror_row)

            primary_row = Adw.SwitchRow(
                title="Primario",
                subtitle="Ancla del layout y origen del espejo",
            )
            primary_row.set_active(monitor.name == primary)
            primary_row.connect(
                "notify::active",
                lambda row, _param, name=monitor.name: self._on_primary_toggled(name, row.get_active()),
            )
            group.add(primary_row)

            position_row = Adw.ActionRow(title="Posición", subtitle=f"{monitor.x} × {monitor.y}")
            self.position_rows[monitor.name] = position_row
            group.add(position_row)

            for row in (
                resolution_row,
                refresh_row,
                scale_row,
                rotation_row,
                mirror_row,
                primary_row,
            ):
                row.set_sensitive(not monitor.disabled)

        self._updating = False

    def _get(self, name: str) -> layout.MonitorState | None:
        for monitor in self.monitors:
            if monitor.name == name:
                return monitor
        return None

    def _after_edit(self, rebuild: bool = False) -> None:
        self.dirty = True
        self._update_canvas()
        self._update_status()
        if rebuild:
            GLib.idle_add(self._rebuild_sidebar_idle)

    def _rebuild_sidebar_idle(self) -> bool:
        self._rebuild_sidebar()
        return False

    def _on_active_toggled(self, name: str, active: bool) -> None:
        if self._updating:
            return
        monitor = self._get(name)
        if monitor is None:
            return

        if not active:
            remaining = [
                other for other in self.monitors if not other.disabled and other.name != name
            ]
            if not remaining:
                self._toast("Debe quedar al menos un monitor activo.")
                GLib.idle_add(self._rebuild_sidebar_idle)
                return

        monitor.disabled = not active
        if monitor.disabled:
            monitor.mirror = ""
            if monitor.primary:
                monitor.primary = False
                layout.ensure_primary(self.monitors, None)
        self._after_edit(rebuild=True)

    def _on_resolution_changed(self, name: str, index: int) -> None:
        if self._updating:
            return
        monitor = self._get(name)
        if monitor is None:
            return
        resolutions = _resolution_options(monitor)
        if not (0 <= index < len(resolutions)):
            return
        width, height = resolutions[index]
        if (width, height) == (monitor.width, monitor.height):
            return
        monitor.width, monitor.height = width, height
        refreshes = _refresh_options(monitor)
        if refreshes:
            monitor.refresh = min(refreshes, key=lambda value: abs(value - monitor.refresh))
        self._after_edit(rebuild=True)

    def _on_refresh_changed(self, name: str, index: int) -> None:
        if self._updating:
            return
        monitor = self._get(name)
        if monitor is None:
            return
        values = _refresh_options(monitor)
        if 0 <= index < len(values):
            monitor.refresh = values[index]
            self._after_edit()

    def _on_scale_changed(self, name: str, index: int) -> None:
        if self._updating:
            return
        monitor = self._get(name)
        if monitor is None:
            return
        values = _scale_options(monitor)
        if 0 <= index < len(values):
            monitor.scale = values[index]
            self._after_edit()

    def _on_rotation_changed(self, name: str, index: int) -> None:
        if self._updating:
            return
        monitor = self._get(name)
        if monitor is None:
            return
        if index in (0, 1, 2, 3):
            monitor.transform = index
            self._after_edit()

    def _on_mirror_changed(self, name: str, index: int) -> None:
        if self._updating:
            return
        monitor = self._get(name)
        if monitor is None:
            return
        options = [""] + [
            other.name
            for other in self.monitors
            if other.name != monitor.name and not other.disabled
        ]
        if monitor.mirror and monitor.mirror not in options:
            options.append(monitor.mirror)
        if not (0 <= index < len(options)):
            return
        monitor.mirror = options[index]
        if monitor.mirror:
            target = self._get(monitor.mirror)
            if target is not None:
                monitor.x, monitor.y = target.x, target.y
                monitor.scale = target.scale
                monitor.transform = target.transform
                if any(
                    mode.width == target.width and mode.height == target.height
                    for mode in monitor.available_modes
                ):
                    monitor.width, monitor.height = target.width, target.height
                    monitor.refresh = target.refresh
        self._after_edit(rebuild=True)

    def _on_primary_toggled(self, name: str, active: bool) -> None:
        if self._updating:
            return
        if active:
            layout.ensure_primary(self.monitors, name)
        else:
            other = next(
                (
                    monitor.name
                    for monitor in self.monitors
                    if not monitor.disabled and monitor.name != name
                ),
                None,
            )
            layout.ensure_primary(self.monitors, other)
        self._after_edit(rebuild=True)

    def _on_canvas_change(self, monitor: layout.MonitorState, _committed: bool) -> None:
        self.dirty = True
        row = self.position_rows.get(monitor.name)
        if row is not None:
            row.set_subtitle(f"{monitor.x} × {monitor.y}")
        self._update_status()

    def _update_canvas(self) -> None:
        self.canvas.set_monitors(self.monitors, layout.primary_name(self.monitors))

    def _update_status(self) -> None:
        active = len([monitor for monitor in self.monitors if not monitor.disabled])
        mode = layout.detect_mode(self.monitors)
        label = layout.QUICK_MODE_LABELS.get(mode, mode)
        suffix = " · cambios sin aplicar" if self.dirty else ""
        self.status_label.set_text(f"{active} monitor(es) · {label}{suffix}")
        self.revert_button.set_sensitive(bool(self.snapshot))

    # -------------------------------------------------------------- profiles

    def _load_profiles_into_dropdown(self, selected: str | None = None) -> None:
        names = ["Sin perfil"] + [profile.name for profile in self.store.profiles]
        self._updating = True
        self.profile_dropdown.set_model(Gtk.StringList.new(names))
        target = selected if selected is not None else (self.state.active_profile or "")
        index = names.index(target) if target in names else 0
        self.profile_dropdown.set_selected(index)
        self._updating = False

    def _on_profile_selected(self, dropdown: Gtk.DropDown, _param) -> None:
        if self._updating:
            return
        index = dropdown.get_selected()
        if index <= 0:
            self._selected_profile_name = ""
            return
        names = [profile.name for profile in self.store.profiles]
        if not (0 <= index - 1 < len(names)):
            return
        profile = self.store.get(names[index - 1])
        if profile is not None:
            self._load_profile(profile)

    def _load_profile(self, profile: profiles.Profile) -> None:
        updated = layout.monitors_from_rules(
            self.monitors,
            [entry.rule for entry in profile.monitors],
        )
        primary = profile.primary or layout.primary_name(updated)
        layout.ensure_primary(updated, primary)
        self.monitors = updated
        self._selected_profile_name = profile.name
        self.dirty = True
        self._update_canvas()
        self._rebuild_sidebar()
        self._update_status()
        self._toast(f"Perfil «{profile.name}» cargado. Pulsa Aplicar para activarlo.")

    def _current_profile_name(self) -> str | None:
        if not self._selected_profile_name:
            return None
        profile = self.store.get(self._selected_profile_name)
        if profile is not None and profile.matches_layout(self.monitors):
            return profile.name
        return None

    def _on_save_profile(self) -> None:
        default = self._selected_profile_name or f"Perfil {len(self.store.profiles) + 1}"
        self._prompt_text(
            "Guardar perfil",
            "Ponle un nombre a la disposición actual.",
            default,
            self._on_save_profile_name,
        )

    def _on_save_profile_name(self, name: str) -> None:
        if self.store.get(name) is not None:
            self._confirm(
                "Sobrescribir perfil",
                f"Ya existe un perfil llamado «{name}». ¿Quieres sobrescribirlo?",
                lambda: self._save_profile(name),
            )
        else:
            self._save_profile(name)

    def _save_profile(self, name: str) -> None:
        profile = core.save_profile(name, self.monitors, self.store, self.state, auto=True)
        self._selected_profile_name = name
        self._load_profiles_into_dropdown(selected=name)
        self._toast(f"Perfil «{profile.name}» guardado.")

    def _manage_profiles(self) -> None:
        dialog = Adw.Dialog()
        dialog.set_title("Perfiles")
        dialog.set_content_width(620)
        dialog.set_content_height(560)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(
                title="Perfiles",
                subtitle=f"{len(self.store.profiles)} guardado(s)",
            )
        )
        close_button = Gtk.Button(label="Cerrar")
        close_button.connect("clicked", lambda _button: dialog.close())
        header.pack_end(close_button)
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()

        group = Adw.PreferencesGroup(
            title="Perfiles guardados",
            description="Aplica un perfil o activa su auto-aplicación al conectar monitores.",
        )
        page.add(group)

        if not self.store.profiles:
            empty = Adw.ActionRow(
                title="Todavía no hay perfiles",
                subtitle="Usa «Guardar perfil actual» en el menú.",
            )
            group.add(empty)

        for profile in self.store.profiles:
            row = Adw.ActionRow(
                title=profile.name,
                subtitle=f"{len(profile.monitors)} monitor(es) · primario {profile.primary or '—'}",
            )

            apply_button = Gtk.Button(label="Aplicar")
            apply_button.add_css_class("flat")
            apply_button.connect(
                "clicked",
                lambda _button, name=profile.name: self._apply_profile_from_manager(name, dialog),
            )
            row.add_suffix(apply_button)

            auto_switch = Gtk.Switch()
            auto_switch.set_active(profile.auto)
            auto_switch.set_valign(Gtk.Align.CENTER)
            auto_switch.set_tooltip_text("Aplicar automáticamente al conectar estos monitores")
            auto_switch.connect(
                "notify::active",
                lambda switch, _param, name=profile.name: self._on_profile_auto(name, switch.get_active()),
            )
            row.add_suffix(auto_switch)

            delete_button = Gtk.Button(icon_name="user-trash-symbolic")
            delete_button.add_css_class("flat")
            delete_button.set_tooltip_text("Eliminar perfil")
            delete_button.connect(
                "clicked",
                lambda _button, name=profile.name: self._on_delete_profile(name, dialog),
            )
            row.add_suffix(delete_button)

            group.add(row)

        files_group = Adw.PreferencesGroup(title="Archivo")
        page.add(files_group)

        export_row = Adw.ActionRow(
            title="Exportar perfiles",
            subtitle="Guardar todos los perfiles en un JSON",
        )
        export_button = Gtk.Button(label="Exportar")
        export_button.add_css_class("flat")
        export_button.connect("clicked", lambda _button: self._on_export())
        export_row.add_suffix(export_button)
        files_group.add(export_row)

        import_row = Adw.ActionRow(
            title="Importar perfiles",
            subtitle="Cargar perfiles desde un JSON",
        )
        import_button = Gtk.Button(label="Importar")
        import_button.add_css_class("flat")
        import_button.connect("clicked", lambda _button: self._on_import())
        import_row.add_suffix(import_button)
        files_group.add(import_row)

        toolbar.set_content(page)
        dialog.set_child(toolbar)
        dialog.present(self)

    def _apply_profile_from_manager(self, name: str, dialog: Adw.Dialog) -> None:
        profile = self.store.get(name)
        if profile is None:
            return
        dialog.close()
        self._load_profile(profile)
        self._apply()

    def _on_profile_auto(self, name: str, active: bool) -> None:
        profile = self.store.get(name)
        if profile is None:
            return
        profile.auto = active
        self.store.save()
        core.refresh_generated(self.store, self.state)
        self._toast("Auto-aplicación actualizada.")

    def _on_delete_profile(self, name: str, dialog: Adw.Dialog) -> None:
        self._confirm(
            "Eliminar perfil",
            f"¿Eliminar el perfil «{name}»?",
            lambda: self._delete_profile(name, dialog),
        )

    def _delete_profile(self, name: str, dialog: Adw.Dialog) -> None:
        self.store.delete(name)
        self.store.save()
        if self.state.active_profile == name:
            self.state.active_profile = ""
            self.state_store.save(self.state)
        if self._selected_profile_name == name:
            self._selected_profile_name = ""
        core.refresh_generated(self.store, self.state)
        self._load_profiles_into_dropdown()
        dialog.close()
        self._toast("Perfil eliminado.")

    # --------------------------------------------------------------- apply

    def _apply(self, record_snapshot: bool = True) -> bool:
        if not self.monitors:
            self._toast("No hay monitores conectados.")
            return False

        previous = [monitor.copy() for monitor in self.monitors]

        primary = layout.primary_name(self.monitors)
        layout.ensure_primary(self.monitors, primary)

        errors = layout.validate(self.monitors)
        if errors:
            self._show_errors("No se puede aplicar la disposición", errors)
            return False

        active_profile = self._current_profile_name()
        try:
            result = core.apply_monitors(
                self.monitors,
                self.store,
                self.state,
                persist=True,
                add_require=False,
                active_profile=active_profile,
                primary=primary,
            )
        except Exception as exc:  # noqa: BLE001 - se muestra al usuario
            self._show_errors("Error al aplicar", [str(exc)])
            return False

        if not result.ok:
            self._show_errors("No se pudo aplicar la disposición", result.errors)
            return False

        if record_snapshot:
            self.snapshot = previous

        self.dirty = False
        self._selected_profile_name = active_profile or ""
        self._toast(
            "Disposición aplicada."
            if not result.warnings
            else "Disposición aplicada con avisos."
        )
        for warning in result.warnings:
            print(f"Aviso: {warning}", file=sys.stderr)
        self._refresh_monitors(force=True)
        self._load_profiles_into_dropdown(selected=self.state.active_profile or None)
        self._check_persistence()
        GLib.idle_add(self._check_outputs)
        return True

    def _revert(self) -> None:
        if not self.snapshot:
            self._toast("No hay una disposición anterior.")
            return
        current = [monitor.copy() for monitor in self.monitors]
        self.monitors = [monitor.copy() for monitor in self.snapshot]
        self.dirty = True
        self._update_canvas()
        self._rebuild_sidebar()
        self._update_status()
        if self._apply(record_snapshot=False):
            self.snapshot = current

    def _on_quick_mode(self, mode: str) -> None:
        try:
            updated = layout.quick_mode(
                mode,
                self.monitors,
                primary=layout.primary_name(self.monitors),
            )
        except ValueError as exc:
            self._toast(str(exc))
            return
        self.monitors = updated
        self._selected_profile_name = ""
        self.dirty = True
        self._update_canvas()
        self._rebuild_sidebar()
        self._update_status()
        self._apply(record_snapshot=True)

    # ---------------------------------------------------------- persistence

    def _check_persistence(self) -> None:
        warning = core.persistence_warning()
        if warning:
            self.banner.set_title("La persistencia no está activada.")
            self.banner.set_tooltip_text(warning)
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

    def _on_enable_persistence(self, dialog: Adw.Dialog | None = None) -> None:
        lua_path = config.hypr_lua_path()
        if not lua_path.exists():
            self._show_errors(
                "No se puede activar la persistencia",
                [f"No existe {lua_path}. HyprDisplay necesita una configuración Lua de Hyprland."],
            )
            return

        body = (
            f"Se añadirá esta línea a {lua_path}:\n\n"
            f"{config.REQUIRE_LINE}\n\n"
            "Antes se creará una copia de seguridad del archivo."
        )
        self._confirm(
            "Activar persistencia",
            body,
            lambda: self._enable_persistence(dialog),
        )

    def _enable_persistence(self, dialog: Adw.Dialog | None = None) -> None:
        try:
            changed, backup = core.enable_persistence()
            core.refresh_generated(self.store, self.state)
        except config.ConfigError as exc:
            self._show_errors("No se pudo activar la persistencia", [str(exc)])
            return

        self.banner.set_revealed(False)
        if dialog is not None:
            dialog.close()
        message = "Persistencia activada."
        if changed and backup is not None:
            message += f" Copia de seguridad: {backup.name}"
        self._toast(message)

    # -------------------------------------------------------------- doctor

    def _doctor(self) -> None:
        checks = core.doctor()

        dialog = Adw.Dialog()
        dialog.set_title("Diagnóstico")
        dialog.set_content_width(620)
        dialog.set_content_height(560)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Diagnóstico", subtitle="Estado de HyprDisplay"))
        close_button = Gtk.Button(label="Cerrar")
        close_button.connect("clicked", lambda _button: dialog.close())
        header.pack_end(close_button)
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Comprobaciones")
        page.add(group)

        for label, ok, detail in checks:
            row = Adw.ActionRow(title=label, subtitle=detail)
            icon = Gtk.Image.new_from_icon_name(
                "emblem-ok-symbolic" if ok else "dialog-error-symbolic"
            )
            icon.set_valign(Gtk.Align.CENTER)
            row.add_suffix(icon)
            group.add(row)

        if not config.has_require_line():
            fix_group = Adw.PreferencesGroup(title="Acciones")
            page.add(fix_group)
            fix_row = Adw.ActionRow(
                title="Activar persistencia",
                subtitle="Añadir el require a hyprland.lua y regenerar el Lua",
            )
            fix_button = Gtk.Button(label="Activar")
            fix_button.add_css_class("suggested-action")
            fix_button.connect(
                "clicked",
                lambda _button: self._on_enable_persistence(dialog),
            )
            fix_row.add_suffix(fix_button)
            fix_group.add(fix_row)

        toolbar.set_content(page)
        dialog.set_child(toolbar)
        dialog.present(self)

    # -------------------------------------------------------------- dialogs

    def _prompt_text(
        self,
        heading: str,
        body: str,
        default: str,
        on_accept,
    ) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        entry = Gtk.Entry()
        entry.set_text(default)
        entry.set_activates_default(True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("accept", "Guardar")
        dialog.set_response_appearance("accept", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("accept")

        def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
            if response != "accept":
                return
            text = entry.get_text().strip()
            if text:
                on_accept(text)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _confirm(self, heading: str, body: str, on_accept) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("accept", "Continuar")
        dialog.set_response_appearance("accept", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("accept")
        dialog.connect(
            "response",
            lambda _dialog, response: on_accept() if response == "accept" else None,
        )
        dialog.present(self)

    def _show_errors(self, heading: str, errors: list[str]) -> None:
        dialog = Adw.AlertDialog(
            heading=heading,
            body="\n".join(f"• {error}" for error in errors),
        )
        dialog.add_response("ok", "Entendido")
        dialog.present(self)

    def _toast(
        self,
        message: str,
        action_label: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(7 if action_label else 4)
        if action_label and action is not None:
            toast.set_button_label(action_label)
            toast.connect("button-clicked", lambda _toast: action())
        self.toast_overlay.add_toast(toast)

    # -------------------------------------------------------------- salidas

    def _check_outputs(self) -> bool:
        """Avisa si Hyprland no expone alguna salida a las aplicaciones."""
        try:
            missing = core.invisible_outputs(self.monitors)
        except hypr.HyprError:
            return False
        if not missing:
            return False
        names = ", ".join(missing)
        self._toast(
            f"Hyprland no expone {names} a las apps (sin barra ni fondo).",
            action_label="Reparar",
            action=self._repair_outputs,
        )
        return False

    def _repair_outputs(self) -> None:
        repaired = core.repair_outputs(self.monitors)
        if repaired:
            self._toast("Salida reinicializada: " + ", ".join(repaired) + ".")
        else:
            self._toast("No se pudo reinicializar la salida.")
        self._refresh_monitors(force=True)

    # ---------------------------------------------------------------- files

    def _on_export(self) -> None:
        dialog = Gtk.FileDialog(title="Exportar perfiles", initial_name="hyprdisplay-profiles.json")
        dialog.save(self, None, self._on_export_done)

    def _on_export_done(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return
        if file is None:
            return
        path = file.get_path()
        if path is None:
            return
        try:
            self.store.export_to(Path(path))
        except config.ConfigError as exc:
            self._show_errors("No se pudo exportar", [str(exc)])
            return
        self._toast("Perfiles exportados.")

    def _on_import(self) -> None:
        dialog = Gtk.FileDialog(title="Importar perfiles")
        dialog.open(self, None, self._on_import_done)

    def _on_import_done(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file is None:
            return
        path = file.get_path()
        if path is None:
            return
        try:
            count = self.store.import_from(Path(path))
            core.refresh_generated(self.store, self.state)
        except config.ConfigError as exc:
            self._show_errors("No se pudo importar", [str(exc)])
            return
        self._load_profiles_into_dropdown(selected=self.state.active_profile or None)
        self._toast(f"{count} perfil(es) importados.")

    # --------------------------------------------------------------- extras

    def _open_config(self) -> None:
        try:
            subprocess.Popen(["xdg-open", str(config.app_dir())])
        except OSError as exc:
            self._show_errors("No se pudo abrir la carpeta", [str(exc)])

    def _on_about(self) -> None:
        about = Adw.AboutDialog(
            application_name="HyprDisplay",
            application_icon="io.github.hyprdisplay.HyprDisplay",
            version=config.VERSION,
            developer_name="HyprDisplay",
            comments="Disposición de monitores con perfiles y modos tipo Windows para Hyprland.",
            license_type=Gtk.License.MIT_X11,
        )
        about.present(self)
