#!/bin/bash
# Publisher April Daily — tahan rosak walau env Hermes di-rebuild (cari venv python terbaru)
cd /home/pc175itubuntu/.hermes/apps/april-daily || exit 1
PY=""
for p in $(ls -t /home/pc175itubuntu/.hermes/installs/*/environments/*/venv/bin/python3 2>/dev/null); do
  if [ -x "$p" ]; then PY="$p"; break; fi
done
[ -z "$PY" ] && PY="$(command -v python3)"
exec "$PY" publish.py >> publish.log 2>&1
