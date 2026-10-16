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


class Obb:
    """Read-only view of the expansion file's assets/AssetBundles/."""

    def __init__(self, path):
        self.zip = zipfile.ZipFile(path) if path and os.path.exists(path) else None
        self.lock = threading.Lock()

    def bundle(self, name):
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
