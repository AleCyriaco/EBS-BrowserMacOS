#!/bin/bash
# build-portable.sh [arm64|x86_64]   (padrao: a arquitetura desta maquina)
# Gera dist-<arch>/EBS-Browser.app PORTATIL — Python + Qt/Chromium + JRE 8 + IcedTea-Web,
# tudo dentro do bundle — e o .zip correspondente. Um build por chip e o menor tamanho
# possivel: universal2 dobraria o Chromium (~250 MB por arquitetura).
# Requisitos: Python 3.13 do python.org (universal2), JDK 8 e OpenWebStart:
#   brew install --cask temurin@8 openwebstart
set -euo pipefail
ARCH="${1:-$(uname -m)}"
case "$ARCH" in arm64|x86_64) ;; *) echo "uso: $0 [arm64|x86_64]"; exit 1;; esac
ROOT="$(cd "$(dirname "$0")" && pwd)"; W="$ROOT/.build"; mkdir -p "$W"
PY="${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.13/bin/python3}"
[ -x "$PY" ] || PY=python3

# 1) venv de build (PySide6 completo + PyInstaller; a poda vem depois, por evidencia)
if [ ! -x "$W/venv/bin/pyinstaller" ]; then
  "$PY" -m venv "$W/venv"
  "$W/venv/bin/pip" install -q -U pip
  "$W/venv/bin/pip" install -q "PySide6==6.11.2" pyinstaller
fi

# 2) runtime Java Web Start: jre/ do JDK 8 (enxugado) + openwebstart.jar (o motor IcedTea-Web)
JRE=""; for h in /Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home/jre \
                 /Library/Java/JavaVirtualMachines/*8*/Contents/Home/jre; do
  [ -x "$h/bin/java" ] && { JRE="$h"; break; }; done
OWS=/Applications/OpenWebStart/openwebstart.jar
[ -n "$JRE" ] && [ -f "$OWS" ] || { echo "falta JDK 8 e/ou OpenWebStart: brew install --cask temurin@8 openwebstart"; exit 1; }
rm -rf "$W/jws"; mkdir -p "$W/jws"; cp -R "$JRE" "$W/jws/jre"; cp "$OWS" "$W/jws/openwebstart.jar"
J="$W/jws/jre"
rm -rf "$J/lib/deploy" "$J/lib/desktop" "$J/lib/javaws.jar" "$J/lib/plugin.jar" "$J/lib/deploy.jar" \
       "$J/lib/jfr" "$J/lib/jfr.jar" "$J/lib/missioncontrol" "$J/lib/visualvm" "$J/lib/ext/nashorn.jar" \
       "$J/lib/ext/jfxrt.jar" "$J/man" "$J/lib/images/icons" 2>/dev/null || true
for b in "$J"/bin/*; do case "$(basename "$b")" in java|keytool) ;; *) rm -f "$b";; esac; done

# 3) PyInstaller (--windowed: o proprio executavel e o app -> icone e nome corretos no Dock/menu)
rm -rf "$W/build-$ARCH" "$ROOT/dist-$ARCH"
"$W/venv/bin/pyinstaller" --noconfirm --log-level ERROR --windowed --name EBS-Browser \
  --icon "$ROOT/EBS-Browser.icns" --target-arch "$ARCH" --osx-bundle-identifier local.ebs-browser \
  --add-data "$ROOT/icon-1024.png:." --distpath "$ROOT/dist-$ARCH" --workpath "$W/build-$ARCH" \
  --specpath "$W/build-$ARCH" "$ROOT/ebs_browser.py"
APP="$ROOT/dist-$ARCH/EBS-Browser.app"

# 4) poda por evidencia (otool), runtime embutido, assinatura ad-hoc, zip
"$ROOT/prune-app.sh" "$APP"
cp -R "$W/jws" "$APP/Contents/Resources/jws"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
ZIP="$ROOT/EBS-Browser-macOS-$ARCH.zip"; rm -f "$ZIP"
( cd "$ROOT/dist-$ARCH" && ditto -c -k --sequesterRsrc --keepParent EBS-Browser.app "$ZIP" )
echo "app: $(du -sh "$APP" | cut -f1)   zip: $(du -sh "$ZIP" | cut -f1)   -> $ZIP"
