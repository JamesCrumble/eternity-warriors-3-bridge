"""Player state the server owns, and the helpers every CGS handler shares.

Glu's server was authoritative for the currencies, the experience and the
inventories: the client saves its own attributes (account_shared, *_basic,
quest progress) but only ever *receives* these, as the fields GameManager.
ParseCommonReward reads from an answer:

    sc_current  hc_current  exp  soulshard  gs  bag_size  items  token  vp

Attributes kept here (strings, as Gluon stores them):
    hc_current                     hard currency, shared by the heroes
    <role>_sc_current <role>_xp    soft currency and experience per hero
    <role>_inventory               {"_incrementId": n, "_inventory": [item, ...]}
    <role>_equipment               [inventory positions]
"""
import base64
import json
import re

from Crypto.Cipher import DES

ROLES = ["mage", "warrior", "monk"]          # EnumRole order; role_current indexes it
START_SC = 1000                               # soft currency a new hero starts with
_DES_KEY = b"ew3gluww"                        # Utils._keyBytes (key and IV)

# Equipment never stacks (PlayerInventory.IsCanDuplicate); everything else does.
_EQUIPMENT = re.compile(r"(^|_)(weapon|helm|armpiece|belt|leggings|shoulder|ring|necklace|armor)(_|$)")


# ---- requests -----------------------------------------------------------------------

def des_decrypt(text):
    """Utils.DesDecrypt: base64, DES-CBC, key = IV = "ew3gluww", PKCS#7."""
    raw = DES.new(_DES_KEY, DES.MODE_CBC, _DES_KEY).decrypt(base64.b64decode(text))
    return raw[:-raw[-1]].decode("utf-8", "replace")


def des_encrypt(text):
    raw = text.encode("utf-8")
    pad = 8 - len(raw) % 8
    return base64.b64encode(DES.new(_DES_KEY, DES.MODE_CBC, _DES_KEY).encrypt(raw + bytes([pad]) * pad)).decode()


def payload_json(msg, field="data"):
    """A DES-encrypted JSON field of a request (battle_start / battle_end "data"), or {}."""
    try:
        return json.loads(des_decrypt(msg[field]))
    except (KeyError, ValueError, TypeError):
        return {}


def error(code):
    """A failed answer: Utils.GetCGSErrorCode reads errorCode, the client shows its message box."""
    return False, {"errorCode": int(code)}   # an int: the CGSMessage path casts it with (int)(double)


# ---- attributes ---------------------------------------------------------------------

class Player:
    """One account's attributes, with typed access; save() writes back what changed."""

    def __init__(self, store, pid):
        self.store, self.pid = store, pid
        p = store.get(pid) or {"attributes": {}}
        self.attrs = p["attributes"]
        self.changed = {}

    def get(self, name, default=None):
        if name in self.changed:
            return self.changed[name]
        return self.attrs.get(name, default)

    def set(self, name, value):
        self.changed[name] = value if isinstance(value, str) else json.dumps(value) if not isinstance(value, int) else str(value)

    def get_int(self, name, default=0):
        try:
            return int(float(self.get(name, default)))
        except (TypeError, ValueError):
            return default

    def save(self):
        if self.changed:
            self.store.set_attributes(self.pid, [{"name": k, "value": v} for k, v in self.changed.items()])
            self.changed = {}

    # ---- the current hero
    @property
    def role(self):
        i = self.get_int("role_current", 1)
        return ROLES[i] if 0 <= i < len(ROLES) else "warrior"

    @property
    def hc(self):
        return self.get_int("hc_current", 0)

    @hc.setter
    def hc(self, v):
        self.set("hc_current", max(0, int(v)))

    @property
    def sc(self):
        return self.get_int(self.role + "_sc_current", START_SC)

    @sc.setter
    def sc(self, v):
        self.set(self.role + "_sc_current", max(0, int(v)))

    @property
    def xp(self):
        return self.get_int(self.role + "_xp", 0)

    @xp.setter
    def xp(self, v):
        self.set(self.role + "_xp", max(0, int(v)))

    # ---- inventory
    def inventory(self):
        try:
            inv = json.loads(self.get(self.role + "_inventory") or "{}")
        except ValueError:
            inv = {}
        inv.setdefault("_inventory", [])
        inv.setdefault("_incrementId", 1 + max([it["_inventoryPos"] for it in inv["_inventory"]] or [-1]))
        return inv

    def save_inventory(self, inv):
        self.set(self.role + "_inventory", json.dumps(inv))

    def equipment(self):
        try:
            return json.loads(self.get(self.role + "_equipment") or "[]")
        except ValueError:
            return []


def stackable(item_id):
    return not _EQUIPMENT.search(item_id)


def new_item(pos, item_id, amount, new=True, **extra):
    it = {"_inventoryPos": pos, "_itemDataId": item_id, "_amount": amount, "_isNew": 1 if new else 0,
          "_fusionLevel": 0, "_evolutionLevel": 0, "_fusionXp": 0}
    it.update(extra)
    return it


def add_item(inv, item_id, amount=1):
    """Adds to the inventory as PlayerInventory.AddItemInventory does; returns the touched entries."""
    touched = []
    if stackable(item_id):
        for it in inv["_inventory"]:
            if it["_itemDataId"] == item_id:
                it["_amount"] += amount
                return [it]
        it = new_item(inv["_incrementId"], item_id, amount)
        inv["_incrementId"] += 1
        inv["_inventory"].append(it)
        return [it]
    for _ in range(amount):
        it = new_item(inv["_incrementId"], item_id, 1)
        inv["_incrementId"] += 1
        inv["_inventory"].append(it)
        touched.append(it)
    return touched


def take_item(inv, item_id, amount):
    """Removes up to amount of a stackable item; returns the touched entries (amount 0 = gone)."""
    for it in list(inv["_inventory"]):
        if it["_itemDataId"] == item_id:
            it["_amount"] = max(0, it["_amount"] - amount)
            if it["_amount"] == 0:
                inv["_inventory"].remove(it)
            return [it]
    return []


def take_positions(inv, positions):
    """Removes whole entries by position; returns them with amount 0 (the client then drops them)."""
    gone = []
    for it in list(inv["_inventory"]):
        if it["_inventoryPos"] in positions:
            inv["_inventory"].remove(it)
            gone.append(dict(it, _amount=0))
    return gone


def item_at(inv, pos):
    for it in inv["_inventory"]:
        if it["_inventoryPos"] == pos:
            return it
    return None


def currencies(pl):
    """The fields every answer that changes money carries."""
    return {"sc_current": pl.sc, "hc_current": pl.hc}
