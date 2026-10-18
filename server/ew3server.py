#!/usr/bin/env python3
"""Stand-in for Glu's Eternity Warriors 3 servers (all retired). FastAPI + one asyncio TCP listener.

The port sends every connection here (port/src/symtab_net.cpp, port/jni/unity_www.cpp):

  :18080  HTTP - the game's WWW requests (original host in the Host header):
            .../serverpost_<tag>.json       start-up switches (no blocker, no maintenance)
            .../DynamicContentInfo.json     asset-bundle tag
            .../AssetBundles/<tag>/<file>   index.version and bundles, out of the OBB
            .../edgeServer                  Gluon load balancer -> our edge
          and the admin API under /admin, documented at /docs (Swagger).
  :18024  Gluon edge (TCP, BSON) - edge.py; game logic in cgs.py.

Run:  server/.venv/bin/python server/ew3server.py [--host 127.0.0.1]
"""
import argparse
import asyncio
import contextlib
import json
import os
import sys
import threading
import zipfile
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import cgs  # noqa: E402
import edge  # noqa: E402
from store import Store  # noqa: E402

HTTP_PORT = 18080
EDGE_PORT = 18024
CDN_ROOT = "http://cdn.ew3.local/ew3"
DEFAULT_OBB = os.path.join(ROOT, "ew3data", "Android", "obb", "com.glu.ewarriors3", "main.4100.com.glu.ewarriors3.obb")

cfg = {"host": "127.0.0.1", "obb": DEFAULT_OBB, "data": os.path.join(ROOT, "ew3data", "server")}
state: Dict[str, Any] = {}


def log(msg):
    print("[http] " + msg, flush=True)


import lzma
import struct

# Minimal 1x1 JPEG for shopBanner requests so the client does not retry 404 in a loop
_TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010101004800480000ffdb004300030202020202030202020303030304"
    "060404040404080606050609080a0a090809090a0c0f0c0a0b0e0b09090d110d0e0f101011100a0c"
    "12131210130f101010ffc9000b080001000101011100ffcc000600101005ffda0008010100003f00"
    "d2cf20ffd9"
)


import bundle_patcher  # noqa: E402


DEFAULT_IPA = os.path.join(ROOT, "31263-Eternity-Warriors-3-v0-1-0.ipa")


class Obb:
    """Read-only view of the expansion file's assets/AssetBundles/ with patched bundle overrides."""

    PATCH_SPECS = [
        (
            "base_uniform_data-levels",
            "7A94C7D5E9965F47EE81033F369EA608",
            "7A94C7D5E9965F47EE81033F369EA60C",
            "Asset",
            bundle_patcher.patch_data_levels,
        ),
        (
            "base_uniform_global_manager",
            "3A4AF260FB256A2335A5307A8B65FEDD",
            "3A4AF260FB256A2335A5307A8B65FEDF",
            "Asset",
            bundle_patcher.patch_global_manager,
        ),
        (
            "base_lvl_greece_1_scene",
            "A3DC8F85CBF75E02813D674C8C8069B3",
            "A3DC8F85CBF75E02813D674C8C8069B4",
            "Scene",
            bundle_patcher.patch_greece_1_scene,
        ),
    ]

    # 11 Asset (enemy0, monster weapons + 9 scene raw) + 22 Scene bundles recovered from v0.1.0 IPA,
    # ordered so all CAB-* and .sharedAssets dependencies are registered before the scenes that reference them.
    IPA_BUNDLE_SPECS = [
        # Enemy characters & monster weapons
        ("base_char_enemy0", "index_characters_enemy0_633B4CE89F537D7048B998093167FD87.unity3d", "633B4CE89F537D7048B998093167FD8A", "Asset"),
        ("base_weapon_monster", "index_weapons_monster_E770A0A65B5D6AD7BD762BF0FECE6778.unity3d", "E770A0A65B5D6AD7BD762BF0FECE677B", "Asset"),
        # Raw (Asset) bundles
        ("base_lvl_greece_raw_2", "greece_raw_2_EBF2959B491ACAFA33C1F6C06FA9E511.unity3d", "EBF2959B491ACAFA33C1F6C06FA9E513", "Asset"),
        ("base_lvl_greece_raw_3", "greece_raw_3_B7619427D40BB73EDAA5077882DD5BBE.unity3d", "B7619427D40BB73EDAA5077882DD5BC0", "Asset"),
        ("base_lvl_china_raw", "china_raw_D3BD22DD3C6C7C47B2DAA2DAFF610D42.unity3d", "D3BD22DD3C6C7C47B2DAA2DAFF610D44", "Asset"),
        ("base_lvl_china_raw_2", "china_raw_2_675E7BBEE93CBB44DADD681DE7003FF9.unity3d", "675E7BBEE93CBB44DADD681DE7003FFB", "Asset"),
        ("base_lvl_china_raw_3", "china_raw_3_6AAD6C7AA77C63174CF5ADFE1EC9292F.unity3d", "6AAD6C7AA77C63174CF5ADFE1EC92931", "Asset"),
        ("base_lvl_china_bridge_raw", "china_bridge_raw_A5FDFAD61C8BBF0425A73B7300C8906A.unity3d", "A5FDFAD61C8BBF0425A73B7300C8906C", "Asset"),
        ("base_lvl_gothic_raw_1", "gothic_raw_1_D5740FF1F7BBC70855419D4E1D906ECA.unity3d", "D5740FF1F7BBC70855419D4E1D906ECC", "Asset"),
        ("base_lvl_gothic_raw_2", "gothic_raw_2_03C540ACF022E80A005BEC23AE2DA23E.unity3d", "03C540ACF022E80A005BEC23AE2DA240", "Asset"),
        ("base_lvl_gothic_raw_3", "gothic_raw_3_CC16F43D350E8F46E92D92B1C4B45700.unity3d", "CC16F43D350E8F46E92D92B1C4B45702", "Asset"),
        # Greece 2 & Boss scenes
        ("base_lvl_greece_cave_scene", "index_world_greece_cave_2CD714F9DF1849491320BEFA94F42C04.unity3d", "2CD714F9DF1849491320BEFA94F42C06", "Scene"),
        ("base_lvl_greece_dungeon_scene", "index_world_greece_dungeon_58BBBC52F68834560FD79F89D705F839.unity3d", "58BBBC52F68834560FD79F89D705F83B", "Scene"),
        ("base_lvl_greece_boss_scene", "index_world_greece_boss_FC43DA94C417B137090DA0B1DFF968E8.unity3d", "FC43DA94C417B137090DA0B1DFF968EA", "Scene"),
        # China 1, 2, Bridge & Boss scenes
        ("base_lvl_china_bamboo_scene", "index_world_china_bomboo_A63A927968E93BD02F34B2B688ADDB01.unity3d", "A63A927968E93BD02F34B2B688ADDB03", "Scene"),
        ("base_lvl_china_bamboo_night_scene", "index_world_china_bamboo_night_068D759EE7126235583E25D9090BEAAB.unity3d", "068D759EE7126235583E25D9090BEAAD", "Scene"),
        ("base_lvl_china_town_scene", "index_world_china_town_E74D8FBD8AF398AD857A86DDEB79D00D.unity3d", "E74D8FBD8AF398AD857A86DDEB79D00F", "Scene"),
        ("base_lvl_china_town_night_scene", "index_world_china_town_night_C0C82836A15943999723770AE9D8EB53.unity3d", "C0C82836A15943999723770AE9D8EB55", "Scene"),
        ("base_lvl_china_bridge_scene", "index_world_china_bridge_CB7E63C87959362524BAF1A5E8318DA1.unity3d", "CB7E63C87959362524BAF1A5E8318DA3", "Scene"),
        ("base_lvl_china_bridge_night_scene", "index_world_china_bridge_night_F06ECF7A1ADEE6247E2F83823B723FDC.unity3d", "F06ECF7A1ADEE6247E2F83823B723FDE", "Scene"),
        ("base_lvl_china_ruin_scene", "index_world_china_ruin_5CF30E0E976EE1108B95732712AC98ED.unity3d", "5CF30E0E976EE1108B95732712AC98EF", "Scene"),
        ("base_lvl_china_temple_scene", "index_world_china_temple_836AEB9235F86FE80C9AD54BC7DCFA31.unity3d", "836AEB9235F86FE80C9AD54BC7DCFA33", "Scene"),
        ("base_lvl_china_boss_scene", "index_world_china_boss_9AA1622CEFF0CF269A4D64E24CFAB6ED.unity3d", "9AA1622CEFF0CF269A4D64E24CFAB6EF", "Scene"),
        # Gothic 1, 2 & Boss scenes
        ("base_lvl_1st_playable_scene", "index_world_1st_playable_0835B60FA2BB67A0F37F630652D60935.unity3d", "0835B60FA2BB67A0F37F630652D60937", "Scene"),
        ("base_lvl_gothic_church_scene", "index_world_gothic_church_7FAE6A448B126420C5D09ACC7F0EAA1A.unity3d", "7FAE6A448B126420C5D09ACC7F0EAA1C", "Scene"),
        ("base_lvl_gothic_dungeon_scene", "index_world_gothic_dungeon_B52CE51EAFB8DBE875FDCBFDD5FA1D49.unity3d", "B52CE51EAFB8DBE875FDCBFDD5FA1D4B", "Scene"),
        ("base_lvl_gothic_grave_scene", "index_world_gothic_grave_8BF20637A0077B48F0816D3F82EADFBC.unity3d", "8BF20637A0077B48F0816D3F82EADFBE", "Scene"),
        ("base_lvl_gothic_grave_night_scene", "index_world_gothic_grave_night_4E4E005F681AF8A6379300C69BF7A56F.unity3d", "4E4E005F681AF8A6379300C69BF7A571", "Scene"),
        ("base_lvl_gothic_swamp_scene", "index_world_gothic_swamp_011AB69FDA96778C8348E50069BA8CE8.unity3d", "011AB69FDA96778C8348E50069BA8CEA", "Scene"),
        ("base_lvl_gothic_swamp_night_scene", "index_world_gothic_swamp_night_ABCB8BEDB850155E9BCABC581F1B8F8F.unity3d", "ABCB8BEDB850155E9BCABC581F1B8F91", "Scene"),
        ("base_lvl_gothic_town_scene", "index_world_gothic_town_F30BD25000596E67723F14AB009AEE54.unity3d", "F30BD25000596E67723F14AB009AEE56", "Scene"),
        ("base_lvl_gothic_town_night_scene", "index_world_gothic_town_night_3D59651340E52B2FD3B9400A0E6139B1.unity3d", "3D59651340E52B2FD3B9400A0E6139B3", "Scene"),
        ("base_lvl_gothic_boss_scene", "index_world_gothic_boss_8EB6E7ABF8536307B3E33FD541A9350D.unity3d", "8EB6E7ABF8536307B3E33FD541A9350F", "Scene"),
    ]

    def __init__(self, path):
        self.zip = zipfile.ZipFile(path) if path and os.path.exists(path) else None
        self.lock = threading.Lock()
        self.overrides: Dict[str, bytes] = {}
        if self.zip:
            try:
                cache_dir = os.path.join(cfg["data"], "bundle_cache")
                os.makedirs(cache_dir, exist_ok=True)
                has_ipa = os.path.exists(DEFAULT_IPA)
                idx_replacements = {}
                for bprefix, orig_hash, patched_hash, btype, patch_fn in self.PATCH_SPECS:
                    orig_name = "%s_%s.unity3d" % (bprefix, orig_hash)
                    patched_name = "%s_%s.unity3d" % (bprefix, patched_hash)
                    cache_path = os.path.join(cache_dir, patched_name)
                    if os.path.exists(cache_path):
                        with open(cache_path, "rb") as f:
                            patched_bytes = f.read()
                    else:
                        raw_bytes = self.zip.read("assets/AssetBundles/" + orig_name)
                        if patch_fn in (bundle_patcher.patch_data_levels, bundle_patcher.patch_global_manager):
                            patched_bytes = patch_fn(raw_bytes, has_ipa=has_ipa)
                        else:
                            patched_bytes = patch_fn(raw_bytes)
                        with open(cache_path, "wb") as f:
                            f.write(patched_bytes)
                    self.overrides[patched_name] = patched_bytes
                    self.overrides[orig_name] = patched_bytes
                    idx_replacements[orig_name] = "%s\t%s\t%d\t./%s\t%s" % (
                        bprefix,
                        patched_hash,
                        len(patched_bytes),
                        patched_name,
                        btype,
                    )
                    log("prepared %s (%d bytes)" % (patched_name, len(patched_bytes)))

                ipa_idx_lines = []
                if has_ipa:
                    obb_shaders = None
                    with zipfile.ZipFile(DEFAULT_IPA, "r") as z_ipa:
                        for bprefix, ipa_fname, conv_hash, btype in self.IPA_BUNDLE_SPECS:
                            conv_name = "%s_%s.unity3d" % (bprefix, conv_hash)
                            cache_path = os.path.join(cache_dir, conv_name)
                            if os.path.exists(cache_path):
                                with open(cache_path, "rb") as f:
                                    conv_bytes = f.read()
                            else:
                                if obb_shaders is None:
                                    raw_sh = self.zip.read("assets/AssetBundles/base_uniform_shaders_6014689C88D86A127B2EE32DE67AD882.unity3d")
                                    obb_shaders = bundle_patcher.extract_obb_shaders(raw_sh)
                                raw_ipa = z_ipa.read("Payload/ewarriors3.app/Data/Raw/AssetBundles/" + ipa_fname)
                                conv_bytes = bundle_patcher.convert_ipa_bundle(raw_ipa, bprefix, btype == "Scene", obb_shaders=obb_shaders)
                                with open(cache_path, "wb") as f:
                                    f.write(conv_bytes)
                            self.overrides[conv_name] = conv_bytes
                            ipa_idx_lines.append(
                                "%s\t%s\t%d\t./%s\t%s" % (bprefix, conv_hash, len(conv_bytes), conv_name, btype)
                            )
                    log("prepared %d recovered IPA bundles from %s" % (len(ipa_idx_lines), os.path.basename(DEFAULT_IPA)))

                raw_idx = self.zip.read("assets/AssetBundles/index.version").decode("utf-8")
                new_lines = []
                for line in raw_idx.splitlines():
                    replaced = False
                    for orig_name, rep_line in idx_replacements.items():
                        if orig_name in line:
                            new_lines.append(rep_line)
                            replaced = True
                            break
                    if not replaced:
                        new_lines.append(line)
                new_lines.extend(ipa_idx_lines)
                self.overrides["index.version"] = ("\n".join(new_lines) + "\n").encode("utf-8")
            except Exception as e:
                log("warning: could not patch bundles: %s" % e)

    def bundle(self, name):
        if name in self.overrides:
            return self.overrides[name]
        if not self.zip:
            return None
        with self.lock:
            try:
                return self.zip.read("assets/AssetBundles/" + name)
            except KeyError:
                return None


@contextlib.asynccontextmanager
async def lifespan(app):
    os.makedirs(cfg["data"], exist_ok=True)
    state["store"] = Store(cfg["data"])
    for pid in list(state["store"].players()):
        cgs.ensure_starter_profile(state["store"], pid)
    state["obb"] = Obb(cfg["obb"])
    if not state["obb"].zip:
        log("warning: no OBB at %s - bundles will 404" % cfg["obb"])
    srv = await edge.start(cfg["host"], EDGE_PORT, state["store"])
    yield
    srv.close()


app = FastAPI(title="Eternity Warriors 3 server",
              description="Stand-in for Glu's retired backend. Game traffic: the catch-all route below and the "
                          "Gluon edge on TCP :18024. Everything under /admin is for people.",
              version="0.1", lifespan=lifespan)


# ---- admin API ---------------------------------------------------------------

class PlayerSummary(BaseModel):
    playerId: str
    loginId: str
    nickName: str
    attributes: List[str]


class AttributeValue(BaseModel):
    value: Any


@app.get("/admin/players", response_model=List[PlayerSummary], tags=["admin"])
def list_players():
    """Every account the server has seen, with the names of its saved attributes."""
    return [PlayerSummary(playerId=pid, loginId=p["loginId"], nickName=p.get("nickName", ""),
                          attributes=sorted(p["attributes"]))
            for pid, p in state["store"].players().items()]


@app.get("/admin/players/{player_id}/attributes", tags=["admin"])
def get_attributes(player_id: str) -> Dict[str, Any]:
    """The player's save, attribute by attribute (values as the game wrote them)."""
    p = state["store"].get(player_id)
    if not p:
        raise HTTPException(404, "no such player")
    return p["attributes"]


@app.put("/admin/players/{player_id}/attributes/{name}", tags=["admin"])
def put_attribute(player_id: str, name: str, body: AttributeValue):
    """Overwrite one attribute. The game reads it at the next login."""
    if not state["store"].get(player_id):
        raise HTTPException(404, "no such player")
    state["store"].set_attributes(player_id, [{"name": name, "value": body.value}])
    return {"ok": True}


@app.delete("/admin/players/{player_id}", tags=["admin"])
def delete_player(player_id: str):
    """Forget an account entirely; the device gets a fresh one at the next login."""
    if state["store"].players().pop(player_id, None) is None:
        raise HTTPException(404, "no such player")
    state["store"].save()
    return {"ok": True}


@app.get("/admin/cgs/log", tags=["admin"])
def cgs_log(limit: int = 50, message_type: Optional[str] = None):
    """Recent Custom Game Server messages and the answers they got."""
    items = [e for e in cgs.log_entries if not message_type or e["type"] == message_type]
    return items[-limit:]


@app.get("/admin/edge/log", tags=["admin"])
def edge_log(limit: int = 50):
    """Recent Gluon edge traffic, decoded."""
    return json.loads(json.dumps(edge.journal[-limit:], default=str))


# ---- the game's HTTP ---------------------------------------------------------

def server_post():
    # The client prepends "http://ew3-and." itself (Config.edgeDistribtorUri*), so: bare host:port/path.
    edge_uri = "lb.ew3.local:8015/edgeServer"
    return {
        "BlockerPolicy": "None",
        "BlockerURLGroup": {},
        "GluOnConfig": {
            "ServerName": "PROD",
            "CloudFront": CDN_ROOT,
            "EdgePoint": {k: edge_uri for k in ("stage1", "stage2", "stage3", "stage4", "sub", "prod")},
        },
        "SpecialOptions": {"EnableGluAnalytic": "false"},
        "3rdKeys": {
            "KeyAD": {"appID": "", "zoneID": "", "secretKey": ""},
            "KeyTJ": {"appID": "", "secretKey": "", "ppeID": ""},
        },
        "ForceUpdate": {"ForceUpdateEnable": "no", "ForceUpdateURL": ""},
        "ServerMaintain": {"ServerMaintainEnable": "no", "ServerMaintainURL": ""},
    }


@app.api_route("/{path:path}", methods=["GET", "POST"], tags=["game"], include_in_schema=True)
async def game(path: str, request: Request):
    """Whatever the game asked any of Glu's hosts for (the host is in the Host header)."""
    await request.body()
    name = path.rsplit("/", 1)[-1]
    host = request.headers.get("host", "?")
    if name.startswith("serverpost"):
        resp = JSONResponse(server_post())
    elif name == "DynamicContentInfo.json":
        # The client parses the previous answer's tag with Convert.ToInt32, so it must be numeric.
        resp = JSONResponse({"AssetBundlesTag": "1", "EraseCacheBuildTag": "0"})
    elif name == "edgeServer":
        resp = JSONResponse({"status": "SUCCESS", "host": "127.0.0.1", "port": edge.GUEST_PORT})
    elif "/AssetBundles/" in "/" + path and state["obb"].bundle(name) is not None:
        resp = Response(state["obb"].bundle(name), media_type="application/octet-stream")
    elif name.endswith(".jpg") or "/shopBanner/" in "/" + path:
        resp = Response(_TINY_JPEG, media_type="image/jpeg")
    else:
        resp = Response("not served: " + path, status_code=404)
    log("%s %s%s -> %d" % (request.method, host, "/" + path, resp.status_code))
    return resp


def main():
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=cfg["host"])
    ap.add_argument("--obb", default=cfg["obb"])
    ap.add_argument("--data", default=cfg["data"])
    a = ap.parse_args()
    cfg.update(host=a.host, obb=a.obb, data=a.data)
    uvicorn.run(app, host=a.host, port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
