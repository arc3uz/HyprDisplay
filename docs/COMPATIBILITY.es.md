# Compatibilidad

[English](COMPATIBILITY.md) · **Español**

HyprDisplay no es una aplicación universal de monitores: es una herramienta para
**Hyprland con el config manager Lua**. Esta página documenta qué funciona, qué
no y cómo comprobarlo antes de instalar.

## Resumen

| Entorno | Soporte |
|---|---|
| Hyprland 0.55+ con configuración Lua (`hyprland.lua` + `config/`) | **Soportado** |
| Hyprland 0.55+ con configuración Lua en otro layout | Parcial: requiere ajustar rutas a mano |
| Hyprland 0.54 o anterior | **No soportado** |
| Hyprland con `hyprland.conf` clásico | **No soportado** |
| Sway, i3, GNOME, KDE Plasma, X11 | **No soportado** |

La distro no importa: funciona igual en Arch/CachyOS, Fedora, Debian/Ubuntu,
openSUSE, etc., siempre que se cumplan los requisitos de abajo. Lo que importa
es el compositor y el formato de configuración.

## Requisitos duros

| Requisito | Por qué | Qué falla si no está |
|---|---|---|
| Hyprland 0.55+ | `hl.monitor`, `hl.get_monitors` y `hyprctl eval` con Lua | `doctor` marca **FAIL** en *Versión mínima* |
| Config manager Lua activo | La app aplica reglas con `hyprctl eval` | *Configuración Lua*: no detectada |
| `~/.config/hypr/hyprland.lua` | Ahí se inserta el `require` | `doctor --fix` lanza un error de configuración |
| `~/.config/hypr/config/binds.lua` | Ahí se instala el atajo `SUPER + P` | `hyprdisplay shortcut` no encuentra el archivo |
| `hyprctl` en `PATH`, mismo usuario y sesión | Toda la comunicación con Hyprland | Error «hyprctl no está instalado» |
| GTK 4 + libadwaita 1 + PyGObject + pycairo | Interfaz gráfica | La GUI no abre; la CLI sigue funcionando |
| Sesión Wayland | Socket de Hyprland y `wl_output` | No se pueden aplicar reglas |

## Comprobación rápida

```bash
hyprdisplay doctor
```

Salida esperada en un equipo compatible:

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

Si *Versión mínima* o *Configuración Lua* fallan, la app puede abrir la interfaz
pero no podrá aplicar ni persistir la disposición.

## Portabilidad entre equipos

Lo que **sí** es independiente del hardware y del usuario:

- Rutas basadas en `XDG_CONFIG_HOME`, `XDG_DATA_HOME` y `Path.home()`.
- `install.sh` usa `PREFIX` (por defecto `~/.local`) y genera el lanzador con la
  ruta real de instalación.
- Los perfiles identifican monitores por EDID y puerto, no por índice.

Lo que **no** se debe copiar entre equipos:

- `~/.config/hyprdisplay/profiles.json` y `state.json`: contienen el EDID y los
  modos del panel anterior.
- `~/.config/hypr/config/monitor-profiles.lua`: reglas generadas para ese
  hardware.

Tras migrar, borra esos tres archivos y regenera con `hyprdisplay doctor --fix`
antes de crear perfiles nuevos.

## Dependencias por distro

| Distro | Paquetes |
|---|---|
| Arch / CachyOS | `python-gobject gtk4 libadwaita python-cairo` |
| Fedora | `python3-gobject gtk4 libadwaita python3-cairo` |
| Debian / Ubuntu | `python3-gi gir1.2-gtk-4.0 libadwaita-1-0 python3-cairo` |
| openSUSE | `python3-gobject gtk4 libadwaita1 python3-cairo` |

No se instalan dependencias con `pip` (PEP 668): se usan los paquetes del sistema
para que coincidan con las versiones de GTK que ya usa el escritorio.

## Limitaciones conocidas

- No genera configuración para `hyprland.conf` clásico.
- Asume que los binds están en `config/binds.lua` y usa `hl.bind`.
- El atajo por defecto (`SUPER + P`) se puede cambiar con `hyprdisplay shortcut`,
  pero el script de instalación solo añade ese.
- Flatpak no es viable: la app necesita acceso directo al socket de Hyprland.
- Si Hyprland cambia la API Lua en el futuro, habrá que actualizar la app.

## Mejoras futuras

1. Backend para `hyprland.conf` (líneas `monitor=` en lugar de `hl.monitor`).
2. Detección automática del layout de binds (`binds.lua`, `keybinds.lua`, `.conf`).
3. Instalación de dependencias por distro desde `install.sh`.
4. Empaquetado AUR para Arch/CachyOS.
