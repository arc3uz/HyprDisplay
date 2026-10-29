# Compatibility

**English** · [Español](COMPATIBILITY.es.md)

HyprDisplay is not a universal monitor application: it is a tool for
**Hyprland with the Lua config manager**. This page documents what works,
what does not, and how to check before installing.

## Summary

| Environment | Support |
|---|---|
| Hyprland 0.55+ with a Lua configuration (`hyprland.lua` + `config/`) | **Supported** |
| Hyprland 0.55+ with a Lua configuration in a different layout | Partial: requires adjusting the paths manually |
| Hyprland 0.54 or older | **Not supported** |
| Hyprland with a classic `hyprland.conf` | **Not supported** |
| Sway, i3, GNOME, KDE Plasma, X11 | **Not supported** |

The distro does not matter: it works the same on Arch/CachyOS, Fedora,
Debian/Ubuntu, openSUSE, etc., as long as the requirements below are met.
What matters is the compositor and the configuration format.

## Hard requirements

| Requirement | Why it is needed | What fails when missing |
|---|---|---|
| Hyprland 0.55+ | `hl.monitor`, `hl.get_monitors` and `hyprctl eval` with Lua | *doctor* reports **FAIL** on *Versión mínima* |
| Lua config manager active | The app applies rules with `hyprctl eval` | *Configuración Lua*: not detected |
| `~/.config/hypr/hyprland.lua` | The `require` is inserted there | `doctor --fix` raises a config error |
| `~/.config/hypr/config/binds.lua` | The `SUPER + P` shortcut is installed there | `hyprdisplay shortcut` cannot find the file |
| `hyprctl` on `PATH`, same user and session | Every interaction with Hyprland | Error «hyprctl no está instalado» |
| GTK 4 + libadwaita 1 + PyGObject + pycairo | Graphical interface | The GUI will not open; the CLI keeps working |
| Wayland session | The Hyprland socket and `wl_output` | Rules cannot be applied |

## Quick check

```bash
hyprdisplay doctor
```

Expected output on a compatible machine (labels are printed by the tool in
Spanish):

```text
[OK  ] Hyprland: v0.56.2
[OK  ] Versión mínima: 0.56.2 ≥ 0.55
[OK  ] Configuración Lua: Activa
[OK  ] hyprland.lua: /home/usuario/.config/hypr/hyprland.lua
[OK  ] Línea require: require("config.monitor-profiles")
[OK  ] Archivo generado: /home/usuario/.config/hypr/config/monitor-profiles.lua
[OK  ] Errores de configuración: Sin errores
[OK  ] Perfiles: 1 guardado(s) en /home/usuario/.config/hyprdisplay/profiles.json
[OK  ] Monitores: eDP-1
```

If *Versión mínima* or *Configuración Lua* fail, the app can still open its
interface but will not be able to apply or persist the layout.

## Portability between machines

What **is** independent of the hardware and the user:

- Paths based on `XDG_CONFIG_HOME`, `XDG_DATA_HOME` and `Path.home()`.
- `install.sh` uses `PREFIX` (default `~/.local`) and generates the launcher
  with the real installation path.
- Profiles identify monitors by EDID and port, not by index.

What must **not** be copied between machines:

- `~/.config/hyprdisplay/profiles.json` and `state.json`: they contain the
  EDID and the modes of the previous panel.
- `~/.config/hypr/config/monitor-profiles.lua`: rules generated for that
  hardware.

After migrating, delete those three files and regenerate with
`hyprdisplay doctor --fix` before creating new profiles.

## Dependencies by distro

| Distro | Packages |
|---|---|
| Arch / CachyOS | `python-gobject gtk4 libadwaita python-cairo` |
| Fedora | `python3-gobject gtk4 libadwaita python3-cairo` |
| Debian / Ubuntu | `python3-gi gir1.2-gtk-4.0 libadwaita-1-0 python3-cairo` |
| openSUSE | `python3-gobject gtk4 libadwaita1 python3-cairo` |

Dependencies are not installed with `pip` (PEP 668): system packages are used
so they match the GTK versions your desktop already runs.

## Known limitations

- Does not generate configuration for a classic `hyprland.conf`.
- Assumes the keybinds live in `config/binds.lua` and use `hl.bind`.
- The default shortcut (`SUPER + P`) can be replaced with
  `hyprdisplay shortcut`, but the install script only adds that one.
- Flatpak is not viable: the app needs direct access to the Hyprland socket.
- If Hyprland changes the Lua API in the future, the app will need updating.

## Future improvements

1. Backend for the classic `hyprland.conf` (`monitor=` lines instead of
   `hl.monitor`).
2. Automatic detection of the keybinds layout (`binds.lua`, `keybinds.lua`,
   `.conf`).
3. Installing per-distro dependencies from `install.sh`.
4. AUR packaging for Arch/CachyOS.
