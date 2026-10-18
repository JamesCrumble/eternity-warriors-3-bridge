#!/bin/bash
# Builds a release bundle in release/v<version>/ (git-ignored), the files to attach to a GitHub release:
#   Eternity-Warriors-3-Bridge-<v>.apk        release-signed APK (not debuggable)
#   Eternity-Warriors-3-Bridge-<v>-src.zip    source: tracked and not-yet-committed files of the working tree (what the APK was built from)
#   qemu-patches.zip                          the patches libqemu.so (QEMU, GPL-2.0) was built with
#   *-extended.ew3x                           the extended pack from gamebin/, if there is one
#   INSTALL.txt, RELEASE_NOTES.md, SHA256SUMS
# The game's own files are the player's and are never part of a release.
# Usage: tools/make_release.sh   (run from WSL; needs apk/build/sysroot inputs, see apk/make_sysroot.sh)
set -euo pipefail
P=$(cd "$(dirname "$0")/.." && pwd)
source "$P/env.sh"
cd "$P"
VER=$(grep -o 'versionName="[^"]*"' apk/AndroidManifest.xml | head -1 | cut -d'"' -f2)
NAME="Eternity-Warriors-3-Bridge"
OUT="$P/release/v$VER"
QEMU_SRC="${QEMU_SRC:-$P/qemu}"
rm -rf "$OUT"; mkdir -p "$OUT"
./build.sh > logs/build.log 2>&1
RELEASE=1 bash apk/build_apk.sh > logs/apk_release.log 2>&1
tail -2 logs/apk_release.log
mv "$NAME-$VER.apk" "$OUT/"
rm -f "$NAME-$VER.apk.idsig"
python3 - "$OUT/$NAME-$VER-src.zip" "$NAME-$VER" <<'PY'
import subprocess, sys, zipfile
out, prefix = sys.argv[1], sys.argv[2]
files = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]).decode().split("\0")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        if f and not f.endswith(".ipa"):
            try:
                z.write(f, prefix + "/" + f)
            except (FileNotFoundError, IsADirectoryError):
                pass
PY
if [ -d "$QEMU_SRC/patches" ]; then
    python3 - "$OUT/qemu-patches.zip" "$QEMU_SRC" <<'PY'
import os, sys, zipfile
out, root = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for name in ("README.md", "Dockerfile", "build_variant.sh"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            z.write(p, "qemu/" + name)
    for base, _, files in os.walk(os.path.join(root, "patches")):
        for f in sorted(files):
            p = os.path.join(base, f)
            z.write(p, "qemu/" + os.path.relpath(p, root))
PY
fi
# The optional extended pack (tools/make_extended.py), a separate attachment.
for f in gamebin/*-extended.ew3x; do [ -f "$f" ] && cp "$f" "$OUT/"; done
cp tools/release_install.txt "$OUT/INSTALL.txt"
[ -f tools/release_notes.md ] && cp tools/release_notes.md "$OUT/RELEASE_NOTES.md"
(cd "$OUT" && sha256sum * | grep -v SHA256SUMS > SHA256SUMS)
ls -la "$OUT"
