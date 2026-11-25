#!/bin/bash
# Copia el código de esta compu a la Pi y reinicia el asistente.
# Se corre en la compu:  bash desplegar.sh            (usa el alias "pi" de ~/.ssh/config)
#                        PI=otro-alias bash desplegar.sh
# No toca lo que vive solo en la Pi: venvs, frases grabadas, registro de gastos.
set -euo pipefail
PI=${PI:-pi}
cd "$(dirname "$0")"
rsync -a --exclude venv --exclude venv-luces --exclude frases --exclude voces \
      --exclude consumo.log --exclude __pycache__ \
      asistente/ systemd "$PI":asistente/
# Los archivos privados (si existen) van a ~/.config/asistente con permisos 600.
for f in privado/perfil.md privado/personas.toml privado/radios.toml; do
  [ -f "$f" ] && rsync -a --chmod=F600 "$f" "$PI":.config/asistente/
done
ssh "$PI" 'sudo systemctl restart asistente-charla && systemctl is-active asistente-charla'
