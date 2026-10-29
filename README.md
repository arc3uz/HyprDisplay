# HyprDisplay

**English** · [Español](README.es.md)

Monitor layout editor for **Hyprland** with a GTK4/libadwaita interface,
persistent profiles and `Win + P`-style quick modes.

Designed for Hyprland configurations based on the **Lua parser**
(Hyprland 0.55+), as used by CachyOS and many dotfiles.

<img src="data/io.github.hyprdisplay.HyprDisplay.svg" width="96" align="right">

## Features

- **Visual editor**: drag the monitors on the canvas to place them; magnetic
  snapping aligns edges automatically.
- **Per-monitor settings**: enable/disable, resolution, refresh rate, scale,
  rotation, mirroring and primary monitor.
- **Windows-style quick modes**:
  - Laptop only
  - Duplicate
  - Extend
  - External only
- **Profiles**: save any layout with a name and load it whenever you want.
- **Auto-apply**: when monitors connect or disconnect, Hyprland applies the
  profile that matches the connected hardware (by EDID and port).
- **Real persistence**: the layout survives reboots and `hyprctl reload`.
- **Full CLI** for scripts and keyboard shortcuts.
- **`SUPER + P` shortcut** to open HyprDisplay, just like `Win + P` on Windows
  (it is installed in `binds.lua` with `hyprdisplay shortcut`).

## Requirements

- **Hyprland 0.55 or newer** with a **Lua** configuration (`hyprland.lua` and
  `config/`). `hyprdisplay doctor` checks the version and warns if the Lua
  config manager is not supported. See [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)
  (currently Spanish-only).
- Python 3.10 or newer.
- PyGObject with GTK 4, libadwaita 1 and pycairo installed as system packages.
- `hyprctl` available on `PATH`.

On Arch/CachyOS:

```bash
sudo pacman -S python-gobject gtk4 libadwaita python-cairo
```

Dependencies are not installed with `pip` (PEP 668); system packages are used
so they match the GTK versions your desktop already runs.

## Installation

From the project root:

```bash
./install.sh
```

This installs to `~/.local`:

- `~/.local/lib/hyprdisplay/` (Python package)
- `~/.local/bin/hyprdisplay` (launcher)
- `~/.local/share/applications/io.github.hyprdisplay.HyprDisplay.desktop`
- `~/.local/share/icons/hicolor/scalable/apps/io.github.hyprdisplay.HyprDisplay.svg`

Then activate persistence in Hyprland:

```bash
hyprdisplay doctor --fix
hyprctl reload
```

`doctor --fix` makes a **backup** of `hyprland.lua` and adds:

```lua
require("config.monitor-profiles")
```

right after `require("config.monitors")`, and generates the file
`~/.config/hypr/config/monitor-profiles.lua`.

To install the `SUPER + P` shortcut (with backup of `binds.lua`):

```bash
hyprdisplay shortcut
```

You can also do everything in one go:

```bash
./install.sh --fix-config --shortcut
```

> If `~/.local/bin` is not on `PATH`, add it so the `SUPER + P` shortcut and
> the `hyprdisplay` command work.

## Using the GUI

```bash
hyprdisplay gui
```

or open **HyprDisplay** from your application menu (the app UI is in Spanish;
labels below show what you will see on screen).

- **Canvas**: drag a monitor to move it. Edges snap magnetically.
- **Right panel**: change resolution, refresh rate, scale, rotation, mirror,
  primary, or disable the monitor.
- **Quick mode buttons**: apply the layout immediately.
- **`SUPER + P`**: opens the app; if it is already open, brings it to front.
- **Aplicar (Apply)** (`Ctrl + Enter`): applies and saves the layout.
- **Revertir (Revert)** (`Ctrl + Z`): go back to the previous layout.
- **Identificar (Identify)** (`Ctrl + I`): shows a large number on each screen.
- **Actualizar (Refresh)** (`F5`): re-reads Hyprland's real state.
- **Menu**: save profile, manage profiles, export/import JSON, diagnostics and
  the configuration folder.

If the banner about persistence not being enabled appears, press
**Activar (Enable)**: the app asks for confirmation before modifying
`hyprland.lua` and creates a backup.

### Profiles and auto-apply

When you save a profile, the EDID of each monitor (`description|serial`) and
the port where it was connected are stored. When monitors connect, Hyprland
looks for the automatic profile that best matches:

1. EDID match on the same port (highest score).
2. EDID match on a different port.
3. Port and description match if the serial changed.

Profiles marked as **manual** are not applied automatically.

## CLI

```bash
hyprdisplay status              # current state
hyprdisplay status --json       # state as JSON
hyprdisplay list                # saved profiles
hyprdisplay list --json

hyprdisplay save escritorio     # saves the current layout
hyprdisplay apply escritorio    # applies a profile
hyprdisplay delete escritorio   # deletes a profile

hyprdisplay mode extend         # internal | duplicate | extend | external
hyprdisplay cycle               # next quick mode (manual, optional)
hyprdisplay revert              # back to the previous layout

hyprdisplay doctor              # checks the installation
hyprdisplay doctor --fix        # activates persistence and regenerates the Lua
hyprdisplay repair              # re-initializes outputs invisible to apps
hyprdisplay shortcut            # installs/updates SUPER+P in binds.lua

hyprdisplay export perfiles.json
hyprdisplay import perfiles.json
```

Useful options:

- `--no-persist`: applies to the running session only, without writing the
  configuration.
- `--fix-config`: adds the `require` if it is missing when applying a profile
  or a mode.

## How persistence works

HyprDisplay writes three things:

| File | Content |
| --- | --- |
| `~/.config/hyprdisplay/profiles.json` | Saved profiles |
| `~/.config/hyprdisplay/state.json` | Active profile, primary, current and previous layout |
| `~/.config/hypr/config/monitor-profiles.lua` | Monitor rules + auto-apply |

`monitor-profiles.lua` is loaded from `hyprland.lua` via the `require` and
contains:

- The rules of the current layout (`hl.monitor({...})`).
- The profiles with their EDID.
- Handlers for `monitor.added`, `monitor.removed` and `hyprland.start` that
  wait 750 ms (so Hyprland finishes detecting the hardware) and apply the
  matching profile.

There is no daemon: everything lives inside Hyprland's configuration, so it
survives reboots and configuration reloads.

> `hyprctl reload` clears monitor rules at runtime and reloads the
> configuration; since the generated Lua contains the current layout, it
> re-applies itself.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| `SUPER + P` | Open HyprDisplay (installed in `binds.lua`) |
| `Ctrl + Enter` | Apply |
| `Ctrl + Z` | Revert |
| `F5` | Refresh |
| `Ctrl + I` | Identify monitors |
| `Ctrl + S` | Save profile |
| `Ctrl + P` | Manage profiles |
| `Ctrl + Q` | Quit |

If you already use `SUPER + P` for something else, change the shortcut in
`~/.config/hypr/config/binds.lua` or install another one with:

```bash
hyprdisplay shortcut --key "SUPER + ALT + P"
```

The entry HyprDisplay installs looks like this:

```lua
hl.bind("SUPER + P",
    hl.dsp.exec_cmd("hyprdisplay gui"))
```

## Project structure

```
hyprdisplay/
  app.py        # Adw application and accelerators
  canvas.py     # Interactive Cairo canvas
  cli.py        # Terminal commands
  config.py     # Metadata, XDG paths, atomic writes, require
  core.py       # Logic shared by GUI and CLI
  hypr.py       # hyprctl wrapper
  layout.py     # Geometry, validation, quick modes
  lua.py        # Lua generation and eval
  profiles.py   # Profiles, EDID and state
  window.py     # Main GTK4 window
data/
  io.github.hyprdisplay.HyprDisplay.desktop
  io.github.hyprdisplay.HyprDisplay.svg
docs/
  COMPATIBILITY.md
tests/
  test_core.py
  test_config.py
  test_hypr.py
  test_layout.py
  test_lua.py
  test_profiles.py
.github/workflows/tests.yml
install.sh
run.py          # Launcher from the source tree
```

## Development and tests

```bash
python3 -m compileall hyprdisplay run.py
python3 -m unittest discover -s tests -v
./run.py doctor
./run.py status
```

The `./run.py` launcher works without installing and uses the package from the
current directory.

## Troubleshooting

**`eval is only supported with the lua config manager`**
HyprDisplay requires Hyprland to use the Lua parser. If your configuration is
a classic `hyprland.conf`, this project cannot apply rules at runtime.

**`hyprctl` cannot find the instance**
Make sure you run HyprDisplay inside the Hyprland session (with
`HYPRLAND_INSTANCE_SIGNATURE` exported by uwsm). The CLI tries to discover the
instance with `hyprctl instances -j`.

**The layout does not survive a reboot**
Check that the `require("config.monitor-profiles")` line exists in
`hyprland.lua` and that the generated file exists:

```bash
hyprdisplay doctor
```

**nwg-displays has no effect**
Recent versions of nwg-displays write hyprlang configuration
(`monitors.conf`), which this Lua setup ignores. Use HyprDisplay or the
generated Lua.

**An external monitor shows no bar or wallpaper**
Hyprland 0.56 may enable a monitor in mirror mode without creating its
`wl_output` object. Wayland clients (Noctalia, `grim`, screenshots) stop
seeing that output even though the monitor works, and it does not reappear
after removing the mirror. Symptoms:

```bash
grim -o HDMI-A-1 /tmp/x.png     # unknown output 'HDMI-A-1'
noctalia msg wallpaper-get HDMI-A-1  # unknown output
```

HyprDisplay avoids the problem by enabling the monitor without a mirror an
instant before mirroring it. If you already hit the issue, re-initialize the
output with:

```bash
hyprdisplay repair
```

The app also shows a notice with the **Reparar (Repair)** button when it
detects the situation. Repairing disables and re-enables the monitor (a brief
blink); windows and the wallpaper rearrange themselves.

**The `SUPER + P` shortcut does nothing**
Verify that `hyprdisplay` is on `PATH` and that the shortcut is in
`binds.lua`:

```bash
command -v hyprdisplay
hyprdisplay shortcut
hyprctl configerrors
```

If you previously used `SUPER + P` for another script, `hyprdisplay shortcut`
replaces that entry (with a backup). You can choose another combination with
`--key`.

**The window opens tiled**
Hyprland places new windows tiled. You can float it with your usual float
shortcut or add a window rule to your configuration:

```lua
hl.window_rule({
    name = "hyprdisplay-float",
    match = { class = "io.github.hyprdisplay.HyprDisplay" },
    float = true,
    size = { 1180, 760 },
    center = true,
})
```

## Uninstall

```bash
./install.sh --uninstall
```

It does not delete your profiles (`~/.config/hyprdisplay/`) nor the `require`
line in `hyprland.lua`. Remove them manually if you want to get rid of
everything.

## Version 1 scope

Included: position, resolution/refresh rate, scale, rotation, mirror,
enable/disable, and primary monitor.

Deferred to version 2: VRR, 10-bit, HDR, color profiles and other advanced
per-monitor properties.

## License

MIT.
