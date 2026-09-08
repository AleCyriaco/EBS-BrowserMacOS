#!/bin/bash
# prune-app.sh <EBS-Browser.app>
# Remove do bundle PyInstaller o que o EBS-Browser NAO carrega, por evidencia: fechamento de
# dependencias (otool -L) a partir dos modulos que o app importa. Compativel com bash 3.2.
# O PyInstaller reescreve os install names para a forma plana "@rpath/QtCore" — o parser
# aceita essa forma e a "QtCore.framework/...". Aborta sem apagar nada se o fechamento nao
# contiver QtCore e QtWebEngineCore. SEMPRE re-assina: bundle modificado sem re-assinar e
# morto pelo kernel no lancamento (Apple Silicon).
set -euo pipefail
shopt -s nullglob
APP="$1"; FW="$APP/Contents/Frameworks"; RS="$APP/Contents/Resources"
PS="$FW/PySide6"; QL="$PS/Qt/lib"; QP="$PS/Qt/plugins"
trap 'codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true' EXIT
KEEP_MODS="QtCore QtGui QtWidgets QtNetwork QtWebEngineCore QtWebEngineWidgets QtWebChannel QtPrintSupport QtOpenGL"
KEEP_PLUG="platforms imageformats iconengines styles tls networkinformation generic"

deps_of() {  # nomes Qt* que um binario referencia (forma plana ou .framework)
  otool -L "$1" 2>/dev/null | awk 'NR>1{print $1}' \
    | grep -oE '(@rpath/|/)Qt[A-Za-z0-9]+(\.framework|$)' | grep -oE 'Qt[A-Za-z0-9]+' | sort -u
}
# 3) fechamento PRIMEIRO (antes de apagar qualquer coisa)
need=" "; queue=""
for m in $KEEP_MODS; do [ -f "$PS/$m.abi3.so" ] && queue="$queue $PS/$m.abi3.so"; done
for f in "$FW"/shiboken6/*.so "$FW"/PySide6/libpyside6*.dylib "$FW"/shiboken6/libshiboken6*.dylib; do queue="$queue $f"; done
proc="$QL/QtWebEngineCore.framework/Versions/A/Helpers/QtWebEngineProcess.app/Contents/MacOS/QtWebEngineProcess"
[ -f "$proc" ] && queue="$queue $proc"
for d in $KEEP_PLUG; do for f in "$QP/$d"/*.dylib; do queue="$queue $f"; done; done
while [ -n "$(echo $queue)" ]; do
  set -- $queue; b="$1"; shift; queue="$*"
  for dep in $(deps_of "$b"); do
    case "$need" in *" $dep "*) ;; *) need="$need$dep "; bin="$QL/$dep.framework/Versions/A/$dep"; [ -f "$bin" ] && queue="$queue $bin";; esac
  done
done
case "$need" in *" QtCore "*) ;; *) echo "ABORT: fechamento sem QtCore — nada apagado"; exit 1;; esac
case "$need" in *" QtWebEngineCore "*) ;; *) echo "ABORT: fechamento sem QtWebEngineCore — nada apagado"; exit 1;; esac
echo "fechamento:$need"
# 1) modulos Python do PySide6 nao importados (em Frameworks e o espelho em Resources)
for f in "$PS"/Qt*.abi3.so; do m=$(basename "$f" .abi3.so); case " $KEEP_MODS " in *" $m "*) ;; *) rm -f "$f" "$PS/$m.pyi" "$RS/PySide6/$m.abi3.so" "$RS/PySide6/$m.pyi";; esac; done
# 2) plugins fora da lista
for d in "$QP"/*; do [ -d "$d" ] || continue; n=$(basename "$d"); case " $KEEP_PLUG " in *" $n "*) ;; *) rm -rf "$d" "$RS/PySide6/Qt/plugins/$n";; esac; done
# 4) frameworks fora do fechamento
for d in "$QL"/*.framework; do n=$(basename "$d" .framework); case "$need" in *" $n "*) ;; *) rm -rf "$d" "$RS/PySide6/Qt/lib/$n.framework";; esac; done
# 5) QML, traducoes, locales do WebEngine (so en/pt/es), restos Python-side
rm -rf "$PS/Qt/qml" "$PS/Qt/translations" "$RS/PySide6/Qt/qml" "$RS/PySide6/Qt/translations"
for x in typesystems include glue scripts; do rm -rf "$RS/PySide6/$x" "$PS/$x"; done
L="$QL/QtWebEngineCore.framework/Versions/A/Resources/qtwebengine_locales"
[ -d "$L" ] && find "$L" -name "*.pak" ! -name "en-US.pak" ! -name "pt-BR.pak" ! -name "pt-PT.pak" ! -name "es.pak" -delete
find "$PS" "$RS/PySide6" -name "*.pyi" -delete 2>/dev/null || true
# 6) symlinks pendurados (o PyInstaller espelha Resources<->Frameworks)
find "$RS" "$FW" -type l ! -exec test -e {} \; -delete 2>/dev/null || true
echo "poda concluida"
