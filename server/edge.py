"""Gluon edge: the TCP half of Glu's backend, as glu.Gluon.EdgeConnection speaks it.

Frame: int32 length (of the rest) | int32 type code | int32 sequence | BSON.
The type code is up to four ASCII characters packed big-endian ("aprq" ->
AuthenticatePlayerRequest); server/generated/gluon_schema.json maps them.
A response echoes the request's `passthrough`, which is how the client pairs them.

Requests without a handler get their XxxResponse with status SUCCESS and no
other fields, and are logged - the log is the list of what is left to do.
"""
import asyncio
import datetime
import json
import os
import struct
import time
import uuid

from bson_codec import Schema, decode
import cgs

HERE = os.path.dirname(os.path.abspath(__file__))
GUEST_PORT = 4024          # what the load balancer tells the client; the port maps it to EDGE_PORT
SCHEMA_PATH = os.path.join(HERE, "generated", "gluon_schema.json")

schema = None
store = None
journal = []               # recent traffic, for the admin API
JOURNAL_MAX = 500


def log(msg):
    print("[edge] " + msg, flush=True)


def note(direction, cls, body):
    journal.append({"t": time.time(), "dir": direction, "type": cls, "body": body})
    del journal[:-JOURNAL_MAX]


def code_int(s):
    n = 0
    for ch in s.encode("ascii"):
        n = (n << 8) | ch
    return n


def code_str(n):
    b = n.to_bytes(4, "big").lstrip(b"\0")
    return b.decode("ascii", "replace")


class Session:
    def __init__(self, writer):
        self.writer = writer
        self.pid = None
        self.seq = 0

    def send(self, cls, obj):
        code = schema.code_of.get(cls)
        if code is None:
            log("no wire code for %s - dropped" % cls)
            return
        body = schema.encode_as(cls, obj)
        payload = struct.pack("<ii", code_int(code), self.seq) + body
        self.seq += 1
        self.writer.write(struct.pack("<i", len(payload)) + payload)
        note("out", cls, obj)


def ok(req, **fields):
    out = {"status": "SUCCESS", "passthrough": req.get("passthrough")}
    out.update(fields)
    return out


def fail(req, error="CANNOT_PROCESS_REQUEST", description="", **fields):
    out = {"status": "FAILURE", "passthrough": req.get("passthrough"), "errorType": error,
           "description": description, "action": "DISCARD"}
    out.update(fields)
    return out


def player_info(pid):
    p = store.get(pid) or {}
    return {"playerId": pid, "nickName": p.get("nickName") or ("Hero" + pid[:4])}


def expire():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)


# ---- handlers: request class -> (session, request) -> response fields --------

def h_authenticate(s, req):
    s.pid, _ = store.login(req.get("loginId") or "anonymous")
    return ok(req, loginId=req.get("loginId"), playerInfo=player_info(s.pid),
              session=uuid.uuid4().hex, expireTime=expire())


def h_create(s, req):
    s.pid, _ = store.login(req.get("loginId") or "anonymous")
    return ok(req, playerInfo=player_info(s.pid), session=uuid.uuid4().hex, expireTime=expire())


def h_time(s, req):
    return ok(req, time=datetime.datetime.now(datetime.timezone.utc))


def h_get_attributes(s, req):
    pid = req.get("playerId") or s.pid
    # Accounts made before the server knew the starting gear get it on their next login.
    if pid == s.pid:
        cgs.ensure_starter_profile(store, pid)
    return ok(req, attributes=store.get_attributes(pid, req.get("attributeNames")), playerInfo=player_info(pid))


def h_set_attributes(s, req):
    pid = req.get("playerId") or s.pid
    store.set_attributes(pid, req.get("attributes") or [])
    cgs.ensure_starter_profile(store, pid)
    return ok(req)


def h_delete_attributes(s, req):
    store.delete_attributes(s.pid)
    return ok(req)


def h_cgs(s, req):
    status, payload = cgs.handle(store, s.pid, req.get("cgsId"), req.get("payload"))
    if status:
        return ok(req, payload=payload)
    return fail(req, payload=payload)


HANDLERS = {
    "AuthenticatePlayerRequest": h_authenticate,
    "CreatePlayerRequest": h_create,
    "GetCurrentUTCTimeRequest": h_time,
    "GetAttributesRequest": h_get_attributes,
    "SetAttributesRequest": h_set_attributes,
    "DeleteAllAttributesRequest": h_delete_attributes,
    "CustomGameServerMessageRequest": h_cgs,
}


def response_class(req_cls):
    if req_cls.endswith("Request"):
        r = req_cls[:-len("Request")] + "Response"
        if r in schema.code_of:
            return r
    return None


async def connection(reader, writer):
    s = Session(writer)
    peer = writer.get_extra_info("peername")
    log("client %s connected" % (peer,))
    try:
        while True:
            head = await reader.readexactly(4)
            n = struct.unpack("<i", head)[0]
            frame = await reader.readexactly(n)
            code, _seq = struct.unpack_from("<ii", frame, 0)
            cls = schema.codes.get(code_str(code), "?" + code_str(code))
            req = decode(frame[8:]) if len(frame) > 8 else {}
            note("in", cls, req)
            rcls = response_class(cls)
            h = HANDLERS.get(cls)
            if h:
                resp = h(s, req)
            else:
                log("unhandled %s %s -> empty SUCCESS" % (cls, json.dumps(req, default=str)[:300]))
                resp = ok(req)
            if rcls:
                s.send(rcls, resp)
            await writer.drain()
    except asyncio.IncompleteReadError:
        pass
    except Exception as e:  # keep the server up; the log shows what broke
        log("connection error: %r" % (e,))
    finally:
        log("client %s gone" % (peer,))
        writer.close()


async def start(host, port, the_store):
    global schema, store
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = Schema(json.load(f))
    store = the_store
    srv = await asyncio.start_server(connection, host, port)
    log("listening on %s:%d (%d message types)" % (host, port, len(schema.codes)))
    return srv
