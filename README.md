# HyprDisplay

Editor de disposición de monitores para **Hyprland** con interfaz GTK4/libadwaita,
perfiles persistentes y modos rápidos al estilo de `Win + P`.

Pensado para configuraciones de Hyprland basadas en el **parser Lua**
(Hyprland 0.55+), típicas de CachyOS y de muchas dotfiles.

<img src="data/io.github.hyprdisplay.HyprDisplay.svg" width="96" align="right">

## Características

- **Editor visual**: arrastra los monitores en el lienzo para colocarlos; el
  ajuste magnético alinea bordes automáticamente.
- **Ajustes por monitor**: activar/desactivar, resolución, frecuencia, escala,
  rotación, espejo y monitor primario.
- **Modos rápidos tipo Windows**:
  - Solo portátil
  - Duplicar
  - Extender
  - Solo externo
- **Perfiles**: guarda cualquier disposición con un nombre y cárgala cuando quieras.
- **Auto-aplicación**: al conectar o desconectar monitores, Hyprland aplica el
  perfil que coincida con el hardware conectado (por EDID y puerto).
- **Persistencia real**: la disposición sobrevive a reinicios y a `hyprctl reload`.
- **CLI completa** para scripts y atajos de teclado.
- **Atajo `SUPER + P`** para abrir HyprDisplay, igual que `Win + P` en Windows
  (se instala en `binds.lua` con `hyprdisplay shortcut`).

## Requisitos

- **Hyprland 0.55 o superior** con configuración **Lua** (`hyprland.lua` y `config/`).
  `hyprdisplay doctor` comprueba la versión y avisa si no soporta el config
  manager Lua. Ver [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).
- Python 3.10 o superior.
- PyGObject con GTK 4, libadwaita 1 y pycairo instalados por el sistema.
- `hyprctl` disponible en `PATH`.

En Arch/CachyOS:

```bash
sudo pacman -S python-gobject gtk4 libadwaita python-cairo
```

No se instalan dependencias con `pip` (PEP 668); se usan los paquetes del sistema.

## Instalación

Desde la raíz del proyecto:

```bash
./install.sh
```

Esto instala en `~/.local`:

- `~/.local/lib/hyprdisplay/` (paquete Python)
- `~/.local/bin/hyprdisplay` (lanzador)
- `~/.local/share/applications/io.github.hyprdisplay.HyprDisplay.desktop`
- `~/.local/share/icons/hicolor/scalable/apps/io.github.hyprdisplay.HyprDisplay.svg`

Después activa la persistencia en Hyprland:

```bash
hyprdisplay doctor --fix
hyprctl reload
```

`doctor --fix` hace una **copia de seguridad** de `hyprland.lua` y añade:

```lua
require("config.monitor-profiles")
```

justo después de `require("config.monitors")`, y genera el archivo
`~/.config/hypr/config/monitor-profiles.lua`.

Para instalar el atajo `SUPER + P` (con copia de seguridad de `binds.lua`):

```bash
hyprdisplay shortcut
```

También puedes hacerlo todo de una vez:

```bash
./install.sh --fix-config --shortcut
```

> Si `~/.local/bin` no está en `PATH`, añádelo para que funcione el atajo
> `SUPER + P` y el comando `hyprdisplay`.

## Uso de la interfaz

```bash
hyprdisplay gui
```

o abre **HyprDisplay** desde el menú de aplicaciones.

- **Lienzo**: arrastra un monitor para moverlo. Los bordes se imantan.
- **Panel derecho**: cambia resolución, frecuencia, escala, rotación, espejo,
  primario o desactiva el monitor.
- **Botones de modo rápido**: aplican la disposición inmediatamente.
- **`SUPER + P`**: abre la app; si ya está abierta, la trae al frente.
- **Aplicar** (`Ctrl + Enter`): aplica y guarda la disposición.
- **Revertir** (`Ctrl + Z`): vuelve a la disposición anterior.
- **Identificar** (`Ctrl + I`): muestra un número grande en cada pantalla.
- **Actualizar** (`F5`): relee el estado real de Hyprland.
- **Menú**: guardar perfil, gestionar perfiles, exportar/importar JSON,
  diagnóstico y carpeta de configuración.

Si aparece el aviso de que la persistencia no está activada, pulsa **Activar**:
la app te pedirá confirmación antes de modificar `hyprland.lua` y creará una
copia de seguridad.

### Perfiles y auto-aplicación

Al guardar un perfil se almacena el EDID de cada monitor (`descripción|serial`)
y el puerto donde estaba conectado. Al conectar monitores, Hyprland busca el
perfil automático que mejor coincida:

1. Coincidencia de EDID en el mismo puerto (puntuación máxima).
2. Coincidencia de EDID en otro puerto.
3. Coincidencia por puerto y descripción si cambió el serial.

Los perfiles marcados como **manual** no se aplican solos.

## CLI

```bash
hyprdisplay status              # estado actual
hyprdisplay status --json       # estado en JSON
hyprdisplay list                # perfiles guardados
hyprdisplay list --json

hyprdisplay save escritorio     # guarda la disposición actual
hyprdisplay apply escritorio    # aplica un perfil
hyprdisplay delete escritorio   # elimina un perfil

hyprdisplay mode extend         # internal | duplicate | extend | external
hyprdisplay cycle               # siguiente modo rápido (manual, opcional)
hyprdisplay revert              # vuelve a la disposición anterior

hyprdisplay doctor              # comprueba la instalación
hyprdisplay doctor --fix        # activa persistencia y regenera el Lua
hyprdisplay repair              # reinicializa salidas invisibles para las apps
hyprdisplay shortcut            # instala/actualiza SUPER+P en binds.lua

hyprdisplay export perfiles.json
hyprdisplay import perfiles.json
```

Opciones útiles:

- `--no-persist`: aplica solo en caliente, sin escribir la configuración.
- `--fix-config`: añade el `require` si falta al aplicar un perfil o modo.

## Cómo funciona la persistencia

HyprDisplay escribe tres cosas:

| Archivo | Contenido |
| --- | --- |
| `~/.config/hyprdisplay/profiles.json` | Perfiles guardados |
| `~/.config/hyprdisplay/state.json` | Perfil activo, primario, layout actual y anterior |
| `~/.config/hypr/config/monitor-profiles.lua` | Reglas de monitor + auto-aplicación |

`monitor-profiles.lua` se carga desde `hyprland.lua` con el `require` y contiene:

- Las reglas del layout actual (`hl.monitor({...})`).
- Los perfiles con su EDID.
- Manejadores de `monitor.added`, `monitor.removed` y `hyprland.start` que
  esperan 750 ms (para que Hyprland termine de detectar el hardware) y aplican
  el perfil coincidente.

No hay demonio: todo vive dentro de la configuración de Hyprland, así que
sobrevive a reinicios y a recargas de configuración.

> `hyprctl reload` borra las reglas de monitor en tiempo de ejecución y vuelve
> a cargar la configuración; como el Lua generado contiene el layout actual,
> este se reaplica solo.

## Atajos

| Atajo | Acción |
| --- | --- |
| `SUPER + P` | Abrir HyprDisplay (instalado en `binds.lua`) |
| `Ctrl + Enter` | Aplicar |
| `Ctrl + Z` | Revertir |
| `F5` | Actualizar |
| `Ctrl + I` | Identificar monitores |
| `Ctrl + S` | Guardar perfil |
| `Ctrl + P` | Gestionar perfiles |
| `Ctrl + Q` | Salir |

Si ya usas `SUPER + P` para otra cosa, cambia el atajo en
`~/.config/hypr/config/binds.lua` o instala otro con:

```bash
hyprdisplay shortcut --key "SUPER + ALT + P"
```

La entrada que instala HyprDisplay tiene esta forma:

```lua
hl.bind("SUPER + P",
    hl.dsp.exec_cmd("hyprdisplay gui"))
```

## Estructura del proyecto

```
hyprdisplay/
  app.py        # Aplicación Adw y aceleradores
  canvas.py     # Lienzo interactivo con Cairo
  cli.py        # Comandos de terminal
  config.py     # Metadatos, rutas XDG, escritura atómica, require
  core.py       # Lógica compartida GUI/CLI
  hypr.py       # Envoltorio de hyprctl
  layout.py     # Geometría, validación, modos rápidos
  lua.py        # Generación de Lua y eval
  profiles.py   # Perfiles, EDID y estado
  window.py     # Ventana principal GTK4
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
run.py          # Lanzador desde el árbol de fuentes
```

## Desarrollo y pruebas

```bash
python3 -m compileall hyprdisplay run.py
python3 -m unittest discover -s tests -v
./run.py doctor
./run.py status
```

El lanzador `./run.py` funciona sin instalar y usa el paquete del directorio
actual.

## Solución de problemas

**`eval is only supported with the lua config manager`**
HyprDisplay necesita que Hyprland use el parser Lua. Si tu configuración es
`hyprland.conf` clásica, este proyecto no puede aplicar reglas en caliente.

**`hyprctl` no encuentra la instancia**
Asegúrate de ejecutar HyprDisplay dentro de la sesión de Hyprland (con
`HYPRLAND_INSTANCE_SIGNATURE` exportada por uwsm). La CLI intenta descubrir la
instancia con `hyprctl instances -j`.

**La disposición no sobrevive al reinicio**
Comprueba que existe la línea `require("config.monitor-profiles")` en
`hyprland.lua` y que el archivo generado existe:

```bash
hyprdisplay doctor
```

**nwg-displays no tiene efecto**
Las versiones recientes de nwg-displays escriben configuración hyprlang
(`monitors.conf`), que este setup Lua ignora. Usa HyprDisplay o el Lua
generado.

**Un monitor externo no muestra barra ni fondo de pantalla**
Hyprland 0.56 puede habilitar un monitor en modo espejo sin crear su objeto
`wl_output`. Las aplicaciones Wayland (Noctalia, `grim`, capturas) dejan de ver
esa salida aunque el monitor funcione y, al quitar el espejo, tampoco reaparece.
Síntomas:

```bash
grim -o HDMI-A-1 /tmp/x.png     # unknown output 'HDMI-A-1'
noctalia msg wallpaper-get HDMI-A-1  # unknown output
```

HyprDisplay evita el problema activando el monitor sin espejo un instante antes
de espejarlo. Si ya te pasó, reinicializa la salida con:

```bash
hyprdisplay repair
```

La app también muestra un aviso con el botón **Reparar** cuando detecta la
situación. Reparar desactiva y reactiva el monitor (parpadeo breve); las
ventanas y el fondo se recolocan solos.

**El atajo `SUPER + P` no hace nada**
Verifica que `hyprdisplay` está en `PATH` y que el atajo está en `binds.lua`:

```bash
command -v hyprdisplay
hyprdisplay shortcut
hyprctl configerrors
```

Si antes usabas `SUPER + P` para otro script, `hyprdisplay shortcut` sustituye
esa entrada (con copia de seguridad). Puedes elegir otra combinación con
`--key`.

**La ventana se abre en mosaico (tiled)**
Hyprland coloca las ventanas nuevas en mosaico. Puedes flotarla con tu atajo
habitual de flotado o añadir una regla de ventana a tu configuración:

```lua
hl.window_rule({
    name = "hyprdisplay-float",
    match = { class = "io.github.hyprdisplay.HyprDisplay" },
    float = true,
    size = { 1180, 760 },
    center = true,
})
```

## Desinstalación

```bash
./install.sh --uninstall
```

No borra tus perfiles (`~/.config/hyprdisplay/`) ni la línea `require` de
`hyprland.lua`. Elimínalos a mano si quieres deshacerte de todo.

## Alcance de la versión 1

Incluido: posición, resolución/frecuencia, escala, rotación, espejo,
activar/desactivar y monitor primario.

Aplazado a la versión 2: VRR, 10 bits, HDR, perfiles de color y otras
propiedades avanzadas por monitor.

## Licencia

MIT.
