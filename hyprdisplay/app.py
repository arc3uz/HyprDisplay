"""Punto de entrada GTK4/Adwaita de HyprDisplay."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import config, core  # noqa: E402
from .window import MainWindow  # noqa: E402

APP_ID = "io.github.hyprdisplay.HyprDisplay"

CSS = b"""
.dim-label {
    opacity: 0.65;
}
"""


class HyprDisplayApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.store = None
        self.state_store = None
        self.state = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._install_style()
        self._install_actions()
        self._install_accels()

        try:
            self.store = core.load_profiles()
            self.state_store, self.state = core.load_state()
        except config.ConfigError as exc:
            self._show_startup_error(str(exc))
            self.quit()

    def do_activate(self) -> None:
        if self.store is None or self.state_store is None or self.state is None:
            return

        window = self.props.active_window
        if window is None:
            window = MainWindow(self, self.store, self.state_store, self.state)
        window.present()

    def _install_style(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _install_accels(self) -> None:
        self.set_accels_for_action("win.apply", ["<Control>Return"])
        self.set_accels_for_action("win.revert", ["<Control>z"])
        self.set_accels_for_action("win.refresh", ["F5"])
        self.set_accels_for_action("win.identify", ["<Control>i"])
        self.set_accels_for_action("win.save-profile", ["<Control>s"])
        self.set_accels_for_action("win.manage-profiles", ["<Control>p"])
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def _install_actions(self) -> None:
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda _action, _param: self.quit())
        self.add_action(quit_action)

    def _show_startup_error(self, message: str) -> None:
        try:
            dialog = Adw.AlertDialog(
                heading="No se pudo iniciar HyprDisplay",
                body=message,
            )
            dialog.add_response("close", "Cerrar")
            dialog.present(None)
        except Exception:  # pragma: no cover - último recurso
            print(f"Error: {message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    app = HyprDisplayApplication()
    # GApplication interpreta los argumentos posicionales como archivos; la GUI
    # no abre archivos, así que solo conservamos el nombre del programa.
    args = list(argv if argv is not None else sys.argv)
    return app.run(args[:1])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
