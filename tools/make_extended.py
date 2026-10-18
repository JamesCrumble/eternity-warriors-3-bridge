#!/usr/bin/env python3
"""Builds the extended pack (.ew3x, a zip) from the iOS build v0.1.0: the AssetBundles the server recovers from the IPA
(33 converted bundles) plus the three patched OBB bundles, exactly as server/ew3server.py caches them. With the pack in
place the server (and the Android app) needs neither the IPA nor any conversion: the levels, enemies and bosses of all
three kingdoms are there out of the box.

  server/.venv-android/bin/python tools/make_extended.py [--ipa IPA] [--obb OBB] [--out FILE]

Defaults: gamebin/31263-Eternity-Warriors-3-v0-1-0.ipa, ew3data/Android/obb/com.glu.ewarriors3/main.4100.*.obb,
gamebin/E-Warriors-3-v4-1-0-cache-extended.ew3x. Layout of the pack: *.unity3d (bundle cache), .has_ipa ("1"), manifest.json.
Where it goes: next to the game's APK/cache (Android: the BridgeGames folder), or unzipped into <data>/bundle_cache (PC).
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ipa", default=os.path.join(ROOT, "gamebin", "31263-Eternity-Warriors-3-v0-1-0.ipa"))
    ap.add_argument("--obb", default=os.path.join(ROOT, "ew3data", "Android", "obb", "com.glu.ewarriors3",
                                                  "main.4100.com.glu.ewarriors3.obb"))
    ap.add_argument("--out", default=os.path.join(ROOT, "gamebin", "E-Warriors-3-v4-1-0-cache-extended.ew3x"))
    a = ap.parse_args()
    for f in (a.ipa, a.obb):
        if not os.path.exists(f):
            sys.exit("missing: " + f)
    work = tempfile.mkdtemp(prefix="ew3x-")
    os.environ["EW3_IPA"] = a.ipa
    os.environ["EW3_BUNDLE_CACHE"] = work
    import ew3server
    ew3server.cfg["data"] = work
    t0 = time.time()
    obb = ew3server.Obb(a.obb)
    if not obb.zip or not ew3server.Obb.extended_ready(work):
        sys.exit("the server did not produce the full set of bundles (see the log above)")
    names = sorted(n for n in os.listdir(work) if n.endswith(".unity3d"))
    manifest = {
        "format": 1,
        "bundles": len(names),
        "source_ipa": os.path.basename(a.ipa),
        "source_ipa_size": os.path.getsize(a.ipa),
        "source_obb": os.path.basename(a.obb),
        "files": {n: {"size": os.path.getsize(os.path.join(work, n)),
                      "sha256": hashlib.sha256(open(os.path.join(work, n), "rb").read()).hexdigest()} for n in names},
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for n in names:
            z.write(os.path.join(work, n), n)
        z.writestr(".has_ipa", "1")
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    print("%d bundles -> %s (%.1f MB, %.0f s)" % (len(names), a.out, os.path.getsize(a.out) / 1e6, time.time() - t0))


main()
