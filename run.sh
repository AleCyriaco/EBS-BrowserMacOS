#!/bin/bash
# EBS-Browser: abre so a instancia EBS configurada. Opcional: ./run.sh http://host:8000
cd "$(dirname "$0")"
exec .venv/bin/python ebs_browser.py "$@"
