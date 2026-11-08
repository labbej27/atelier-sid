#!/bin/bash
# Compile « Atelier SID.app », passe les tests et l'installe dans /Applications.
# Le venv et la compilation restent hors du projet : sur un Bureau synchronisé avec
# iCloud, les fichiers d'un venv peuvent devenir « cachés » et Qt ne trouve plus ses modules.
set -euo pipefail
cd "$(dirname "$0")"
TRAVAIL="$HOME/Library/Caches/AtelierSID"
VENV="$TRAVAIL/venv"
PYTHON="${PYTHON:-/opt/homebrew/bin/python3.12}"
export PYTHONDONTWRITEBYTECODE=1

[ -x "$VENV/bin/python" ] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install -q --only-binary=:all: -r requirements.txt
QT_QPA_PLATFORM=offscreen "$VENV/bin/python" -m pytest -q -p no:cacheprovider tests

rm -rf "$TRAVAIL/icone" && mkdir -p "$TRAVAIL/icone/icone.iconset"
"$VENV/bin/python" creer_icone.py "$TRAVAIL/icone/icone.png"
for t in 16 32 128 256 512; do
    sips -z $t $t "$TRAVAIL/icone/icone.png" --out "$TRAVAIL/icone/icone.iconset/icon_${t}x${t}.png" >/dev/null
    sips -z $((t * 2)) $((t * 2)) "$TRAVAIL/icone/icone.png" --out "$TRAVAIL/icone/icone.iconset/icon_${t}x${t}@2x.png" >/dev/null
done
iconutil -c icns "$TRAVAIL/icone/icone.iconset" -o "$TRAVAIL/icone/AtelierSID.icns"
ATELIER_ICONE="$TRAVAIL/icone/AtelierSID.icns" "$VENV/bin/python" -m PyInstaller --noconfirm --clean \
    --distpath "$TRAVAIL/dist" --workpath "$TRAVAIL/work" atelier_sid.spec

# L'application compilée, avec un environnement aussi pauvre que celui du Finder
env -i HOME="$HOME" PATH=/usr/bin:/bin "$TRAVAIL/dist/Atelier SID.app/Contents/MacOS/Atelier SID" \
    --auto-test "$TRAVAIL/essai"
[ -s "$TRAVAIL/essai/test.sid" ] && rm -rf "$TRAVAIL/essai"

rm -rf "/Applications/Atelier SID.app"
ditto "$TRAVAIL/dist/Atelier SID.app" "/Applications/Atelier SID.app"
rm -rf "$TRAVAIL/dist" "$TRAVAIL/work"
echo "Terminé : /Applications/Atelier SID.app"
