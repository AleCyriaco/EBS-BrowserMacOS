#!/bin/bash
# Gera /Applications/EBS-Browser.app (launcher + icone) apontando para ESTE diretorio.
# Se houver um JDK 8 e o OpenWebStart instalados, embute o runtime Java Web Start no bundle
# (Contents/Resources/jws) — e o que abre o Forms sem depender do OpenWebStart externo.
set -euo pipefail
PROJ="$(cd "$(dirname "$0")" && pwd)"
APP=/Applications/EBS-Browser.app
[ -x "$PROJ/.venv/bin/python" ] || { echo "rode ./install.sh antes"; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/MacOS/EBS-Browser" <<LAUNCHER
#!/bin/bash
# Lancador do EBS-Browser. Log em ~/Library/Logs/EBS-Browser.log
export EBS_BUNDLE="\$(cd "\$(dirname "\$0")/../.." && pwd)"
mkdir -p "\$HOME/Library/Logs"
exec "$PROJ/.venv/bin/python" "$PROJ/ebs_browser.py" "\$@" >> "\$HOME/Library/Logs/EBS-Browser.log" 2>&1
LAUNCHER
chmod +x "$APP/Contents/MacOS/EBS-Browser"
cp "$PROJ/EBS-Browser.icns" "$APP/Contents/Resources/EBS-Browser.icns"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>EBS-Browser</string>
  <key>CFBundleDisplayName</key><string>EBS-Browser</string>
  <key>CFBundleIdentifier</key><string>local.ebs-browser</string>
  <key>CFBundleExecutable</key><string>EBS-Browser</string>
  <key>CFBundleIconFile</key><string>EBS-Browser</string>
  <key>CFBundleIconName</key><string>EBS-Browser</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# --- runtime Java Web Start embutido (opcional, mas necessario para o Forms) ---
JRE=""
for h in /Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home/jre \
         /Library/Java/JavaVirtualMachines/*8*/Contents/Home/jre; do [ -x "$h/bin/java" ] && { JRE="$h"; break; }; done
OWS=/Applications/OpenWebStart/openwebstart.jar
if [ -n "$JRE" ] && [ -f "$OWS" ]; then
  mkdir -p "$APP/Contents/Resources/jws"
  cp -R "$JRE" "$APP/Contents/Resources/jws/jre"
  cp "$OWS" "$APP/Contents/Resources/jws/openwebstart.jar"
  rm -rf "$APP/Contents/Resources/jws/jre/lib/deploy" "$APP/Contents/Resources/jws/jre/lib/desktop" "$APP/Contents/Resources/jws/jre/man" 2>/dev/null || true
  echo "runtime JWS embutido: $(du -sh "$APP/Contents/Resources/jws" | cut -f1) (JRE 8 + openwebstart.jar)"
else
  echo "AVISO: sem JDK 8 e/ou OpenWebStart — o Forms vai depender do OpenWebStart instalado."
  echo "       brew install --cask temurin@8 openwebstart   e rode ./make-app.sh de novo."
fi
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true
echo "criado: $APP  (abra com: open -a EBS-Browser)"
