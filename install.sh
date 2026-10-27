#!/usr/bin/env bash
# Instalador de HyprDisplay para una cuenta de usuario.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
LIBDIR="$PREFIX/lib/hyprdisplay"
BINDIR="$PREFIX/bin"
APPDIR="$PREFIX/share/applications"
ICONDIR="$PREFIX/share/icons/hicolor/scalable/apps"
DESKTOP_FILE="io.github.hyprdisplay.HyprDisplay.desktop"
ICON_FILE="io.github.hyprdisplay.HyprDisplay.svg"

FIX_CONFIG=0
INSTALL_SHORTCUT=0
UNINSTALL=0

for arg in "$@"; do
    case "$arg" in
        --fix-config) FIX_CONFIG=1 ;;
        --shortcut) INSTALL_SHORTCUT=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help)
            cat <<'EOF'
Uso: ./install.sh [opciones]

Opciones:
  --fix-config   Añade require("config.monitor-profiles") a hyprland.lua
                 (con copia de seguridad) y genera el Lua inicial.
  --shortcut     Instala el atajo SUPER+P (abre la app) en config/binds.lua
                 (con copia de seguridad).
  --uninstall    Elimina los archivos instalados. No borra tus perfiles.
  -h, --help     Muestra esta ayuda.

Variables:
  PREFIX         Prefijo de instalación (por defecto ~/.local).
EOF
            exit 0
            ;;
        *)
            echo "Opción desconocida: $arg" >&2
            exit 2
            ;;
    esac
done

if [[ "$UNINSTALL" -eq 1 ]]; then
    rm -rf "$LIBDIR"
    rm -f "$BINDIR/hyprdisplay"
    rm -f "$APPDIR/$DESKTOP_FILE"
    rm -f "$ICONDIR/$ICON_FILE"
    echo "HyprDisplay desinstalado de $PREFIX."
    echo "Tus perfiles y la configuración de Hyprland no se han modificado."
    exit 0
fi

echo "Instalando HyprDisplay en $PREFIX…"

if ! python3 -c 'import gi' >/dev/null 2>&1; then
    echo "Aviso: no se encontró PyGObject (python3-gi)." >&2
fi
if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' >/dev/null 2>&1; then
    echo "Aviso: faltan GTK4 o libadwaita para Python (gtk4 / libadwaita)." >&2
fi

mkdir -p "$BINDIR" "$APPDIR" "$ICONDIR"
rm -rf "$LIBDIR"
mkdir -p "$LIBDIR"
cp -r "$ROOT/hyprdisplay" "$LIBDIR/hyprdisplay"
find "$LIBDIR" -type d -name '__pycache__' -prune -exec rm -rf {} +

cat > "$BINDIR/hyprdisplay" <<EOF
#!/bin/sh
export PYTHONPATH="$LIBDIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m hyprdisplay "\$@"
EOF
chmod 755 "$BINDIR/hyprdisplay"

install -m 644 "$ROOT/data/$DESKTOP_FILE" "$APPDIR/$DESKTOP_FILE"
install -m 644 "$ROOT/data/$ICON_FILE" "$ICONDIR/$ICON_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPDIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Ejecutable: $BINDIR/hyprdisplay"

case ":$PATH:" in
    *":$BINDIR:"*) ;;
    *) echo "Aviso: $BINDIR no está en PATH. Añádelo para usar el atajo SUPER+P." >&2 ;;
esac

if [[ "$FIX_CONFIG" -eq 1 ]]; then
    "$BINDIR/hyprdisplay" doctor --fix
    echo
    echo "Recarga Hyprland para activar la persistencia: hyprctl reload"
else
    echo
    echo "Siguiente paso: activa la persistencia con"
    echo "    $BINDIR/hyprdisplay doctor --fix"
    echo "y abre la interfaz con"
    echo "    $BINDIR/hyprdisplay gui"
fi

if [[ "$INSTALL_SHORTCUT" -eq 1 ]]; then
    "$BINDIR/hyprdisplay" shortcut
    echo "Recarga Hyprland para activar el atajo: hyprctl reload"
fi
