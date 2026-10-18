#!/usr/bin/env bash
# Builds the armhf sysroot qemu-arm runs the game and the server in (assets/sysroot.zip of the APK):
# the NEEDED closure of port/build/ew3, glibc and its loader, and Python 3.8 with the server's pure-Python
# packages. Also builds apk/build/serverroot (the server's own files, assets/serverroot.zip).
# Run in WSL from anywhere. Needs downloads/armhf/debs and downloads/armhf/wheels-android (see PROJECT_STATE.md).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO/apk/build/sysroot"
SRV="$REPO/apk/build/serverroot"
LIBDIRS=("$REPO/sdl-arm/lib" /lib/arm-linux-gnueabihf /usr/lib/arm-linux-gnueabihf /usr/arm-linux-gnueabihf/lib)
STRIP=arm-linux-gnueabihf-strip
GUEST="$REPO/port/build/ew3"

rm -rf "$OUT" "$SRV"
mkdir -p "$OUT/lib/arm-linux-gnueabihf" "$OUT/etc" "$OUT/usr/bin" "$OUT/usr/lib/python3/dist-packages" "$OUT/tmp"

find_lib() {
    local name="$1" d
    for d in "${LIBDIRS[@]}"; do
        [ -e "$d/$name" ] && { readlink -f "$d/$name"; return 0; }
    done
    return 1
}
needed() { readelf -d "$1" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p'; }

declare -A DONE
QUEUE=()
enqueue() { local n="$1"; [ -n "${DONE[$n]:-}" ] && return; DONE[$n]=1; QUEUE+=("$n"); }

# dlopen()ed at runtime, so no NEEDED edge leads to them.
for l in libgcc_s.so.1 libstdc++.so.6 libnss_files.so.2 libSDL2-2.0.so.0; do enqueue "$l"; done
while read -r n; do enqueue "$n"; done < <(needed "$GUEST")

i=0
while [ $i -lt ${#QUEUE[@]} ]; do
    name="${QUEUE[$i]}"; i=$((i + 1))
    case "$name" in ld-linux-armhf.so.3) continue ;; esac
    if ! src="$(find_lib "$name")"; then echo "MISSING: $name" >&2; continue; fi
    cp "$src" "$OUT/lib/arm-linux-gnueabihf/$name"
    while read -r n; do enqueue "$n"; done < <(needed "$src")
done
cp "$(readlink -f /usr/arm-linux-gnueabihf/lib/ld-linux-armhf.so.3)" "$OUT/lib/ld-linux-armhf.so.3"

# Python 3.8 (Ubuntu 20.04 armhf) for the server; its libraries that the sysroot does not have yet.
DEBS="$REPO/downloads/armhf/debs"
for d in "$DEBS"/*.deb; do dpkg-deb -x "$d" "$OUT"; done
# Debian puts the library files under lib/arm-linux-gnueabihf or usr/lib/arm-linux-gnueabihf; both are on the loader path.
for w in "$REPO"/downloads/armhf/wheels-android/*.whl; do
    python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$w" "$OUT/usr/lib/python3/dist-packages"
done
# The NEEDED closure of the Python binary and its extension modules: the debs carry only what Debian splits
# out (libutil, libm ... come from glibc), and nothing may be left to the host: the phone has no other armhf libraries.
have() { [ -e "$OUT/lib/arm-linux-gnueabihf/$1" ] || [ -e "$OUT/usr/lib/arm-linux-gnueabihf/$1" ] || [ -e "$OUT/lib/$1" ]; }
PYQ=("$OUT/usr/bin/python3.8")
while IFS= read -r f; do PYQ+=("$f"); done < <(find "$OUT/usr/lib/python3.8/lib-dynload" -name '*.so')
j=0
while [ $j -lt ${#PYQ[@]} ]; do
    f="${PYQ[$j]}"; j=$((j + 1))
    for n in $(needed "$f"); do
        have "$n" && continue
        if src="$(find_lib "$n")"; then
            cp "$src" "$OUT/lib/arm-linux-gnueabihf/$n"
            PYQ+=("$OUT/lib/arm-linux-gnueabihf/$n")
        else
            echo "MISSING (needed by $(basename "$f")): $n" >&2
            MISSING=1
        fi
    done
done
[ "${MISSING:-0}" = 1 ] && { echo "sysroot is incomplete" >&2; exit 1; }

# Not needed to run the server.
rm -rf "$OUT/usr/share" "$OUT/usr/lib/python3.8/"{test,idlelib,lib2to3,tkinter,turtledemo,ensurepip,distutils,pydoc_data} \
       "$OUT/usr/lib/python3/dist-packages/"*.dist-info
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT/usr/lib/python3/dist-packages" -name '*.pyi' -delete 2>/dev/null || true

echo 'app:x:10000:10000::/data:/bin/sh' > "$OUT/etc/passwd"
echo 'passwd: files' > "$OUT/etc/nsswitch.conf"
printf '127.0.0.1 localhost\n' > "$OUT/etc/hosts"
find "$OUT" -type f \( -name '*.so' -o -name '*.so.*' \) -exec "$STRIP" --strip-unneeded {} + 2>/dev/null || true
"$STRIP" --strip-unneeded "$OUT/usr/bin/python3.8" 2>/dev/null || true
ln -sf python3.8 "$OUT/usr/bin/python3"

# The server's own files (read from the app's private folder, never from the sysroot).
mkdir -p "$SRV/server"
cp "$REPO"/server/*.py "$SRV/server/"
cp -r "$REPO/server/generated" "$SRV/server/generated"

echo "sysroot files: $(find "$OUT" -type f | wc -l)  size: $(du -sh "$OUT" | cut -f1)"
du -a "$OUT" | sort -rn | head -8 || true
