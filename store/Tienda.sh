#!/bin/bash
# Tienda de Apps Knulli - lanzador del frontend pygame.
# Catalogo e instalador de las apps del paquete PORTABLE KNULLI APPS.
set -u

LOG="/tmp/appstore-knulli.log"
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
APP="$SCRIPT_DIR/store.py"

{
    echo "=== $(date) ==="
    echo "SCRIPT_DIR=$SCRIPT_DIR"

    # XDG_RUNTIME_DIR para SDL/audio en Knulli.
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/var/run}"
    export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-pulseaudio}"

    # pylibs del paquete (pygame puede venir del firmware; PYTHONPATH no
    # estorba si no existe).
    PYLIBS="/userdata/system/pylibs"
    export PYTHONPATH="$PYLIBS:${PYTHONPATH:-}"

    cd "$SCRIPT_DIR"
    python3 "$APP" "$@"
    echo "exit=$?"
} >> "$LOG" 2>&1
