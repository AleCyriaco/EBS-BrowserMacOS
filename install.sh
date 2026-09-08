#!/bin/bash
# Cria o venv e instala o PySide6 (Qt + QtWebEngine). Requer Python 3.13 (python.org ou brew).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ necessario"'
"$PY" -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q "PySide6==6.11.2"
echo "venv pronto: $(.venv/bin/python -c 'import PySide6; print("PySide6", PySide6.__version__)')"
echo "Rodar: ./run.sh [http://host:porta]   |   Criar o .app: ./make-app.sh"
