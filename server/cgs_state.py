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
    <role>_token                   {"token_wood": n, ...}
    gearscore                      {"mage": n, "warrior": n, "monk": n, ...}
"""
import base64
import json
import math
import os
import random
import re

from Crypto.Cipher import DES

ROLES = ["mage", "warrior", "monk"]          # EnumRole order; role_current indexes it
START_SC = 1000                               # soft currency a new hero starts with
_DES_KEY = b"ew3gluww"                        # Utils._keyBytes (key and IV)

# Equipment never stacks (PlayerInventory.IsCanDuplicate); everything else does.
_EQUIPMENT = re.compile(r"(^|_)(weapon|helm|armpiece|belt|leggings|shoulder|ring|necklace|armor)(_|$)")

# Load extracted game data tables (items, attributes, enemies, loot, gacha)
_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated", "game_data.json")
GAME_DATA = json.load(open(_DATA_PATH, "r", encoding="utf-8")) if os.path.exists(_DATA_PATH) else {}
ATTR_VALUES = GAME_DATA.get("attr_values") or {}
ITEMS = GAME_DATA.get("items") or {}
ENEMIES = GAME_DATA.get("enemies") or {}
LOOT1 = GAME_DATA.get("loot1") or {}
LOOT2 = GAME_DATA.get("loot2") or {}
LOOT_B1 = GAME_DATA.get("loot_b1") or {}
LOOT_B2 = GAME_DATA.get("loot_b2") or {}
LOOT_B3 = GAME_DATA.get("loot_b3") or {}
GACHA_ITEMS = GAME_DATA.get("gacha_items") or {}
GACHA_GROUPS = GAME_DATA.get("gacha_groups") or {}
FUSION_LIST = GAME_DATA.get("fusion_list") or {}
FUSION_MAX = GAME_DATA.get("fusion_max") or {}
FUSION_CONFIG = GAME_DATA.get("fusion_config") or {}
EVOLUTION_LIST = GAME_DATA.get("evolution_list") or {}


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
    def inventory(self, role=None):
        r = role or self.role
        try:
            inv = json.loads(self.get(r + "_inventory") or "{}")
        except ValueError:
            inv = {}
        inv.setdefault("_inventory", [])
        inv.setdefault("_incrementId", 1 + max([it["_inventoryPos"] for it in inv["_inventory"]] or [-1]))
        return inv

    def save_inventory(self, inv, role=None):
        r = role or self.role
        self.set(r + "_inventory", json.dumps(inv))

    def equipment(self, role=None):
        r = role or self.role
        try:
            return json.loads(self.get(r + "_equipment") or "[]")
        except ValueError:
            return []

    # ---- offerings / gacha tokens (<role>_token)
    def tokens(self, role=None):
        r = role or self.role
        try:
            tok = json.loads(self.get(r + "_token") or "{}")
            return tok if isinstance(tok, dict) else {}
        except ValueError:
            return {}

    def save_tokens(self, tok, role=None):
        r = role or self.role
        self.set(r + "_token", json.dumps(tok))

    def add_token(self, token_id, amount=1, role=None):
        r = role or self.role
        tok = self.tokens(r)
        tok[token_id] = max(0, int(tok.get(token_id, 0)) + int(amount))
        self.save_tokens(tok, r)
        return tok

    # ---- gear score (GS)
    def compute_role_gs(self, role=None):
        r = role or self.role
        inv = self.inventory(r)
        eq_positions = set(int(p) for p in self.equipment(r))
        total = 0
        for it in inv.get("_inventory", []):
            if it.get("_inventoryPos") in eq_positions:
                total += item_score(it)
        return total

    def update_gs(self):
        try:
            gs_obj = json.loads(self.get("gearscore") or "{}")
            if not isinstance(gs_obj, dict):
                gs_obj = {}
        except ValueError:
            gs_obj = {}
        for r in ROLES:
            val = self.compute_role_gs(r)
            gs_obj[r] = val
            gs_obj[r + "_max"] = max(int(gs_obj.get(r + "_max", 0) or 0), val)
        self.set("gearscore", json.dumps(gs_obj))
        return int(gs_obj.get(self.role, 0))

    @property
    def gs(self):
        return self.update_gs()


def is_token(item_id):
    return str(item_id).startswith("token_")


def stackable(item_id):
    return not _EQUIPMENT.search(str(item_id))


def equip_att_list(item_id):
    """Generates EquipAttList JSON (PlayerProfile.CreateAttribute) from ItemData."""
    info = ITEMS.get(str(item_id))
    att_list = []
    if info and info.get("a"):
        for aid, amin, amax in info["a"]:
            if amin == amax:
                val = amin
            else:
                val = random.uniform(amin, amax)
                val = float(int(round(val))) if amin >= 1.0 else round(val, 4)
            att_list.append({"HitParames": aid, "HitValues": val, "IsNature": 1})
    elif not stackable(item_id):
        # Fallback if an equipment item has no explicit attribute rows
        if "weapon" in str(item_id):
            att_list.append({"HitParames": "PHYSICAL_DAMAGE", "HitValues": 35.0, "IsNature": 1})
        else:
            att_list.append({"HitParames": "PHYSICAL_RESIST", "HitValues": 10.0, "IsNature": 1})
    return {"_list": att_list}


def item_sell_value(it):
    """Matches ItemInventory.GetScValue: Mathf.RoundToInt(_lootScore * _sellFactor * _amount)."""
    if not isinstance(it, dict):
        return 0
    info = ITEMS.get(str(it.get("_itemDataId", ""))) or {}
    ls = float(info.get("ls", 50))
    sf = float(info.get("sf", 1.5))
    amt = float(max(1, int(it.get("_amount", 1) or 1)))
    return int(round(ls * sf * amt))


def get_fusion_data(it, fusion_lv=None, evol_lv=None):
    info = ITEMS.get(str(it.get("_itemDataId", ""))) or {}
    lv = int(info.get("lv", 1))
    rare = int(info.get("r", 0))
    ev = int(it.get("_evolutionLevel", 0) or 0) if evol_lv is None else int(evol_lv)
    fu = int(it.get("_fusionLevel", 0) or 0) if fusion_lv is None else int(fusion_lv)
    return FUSION_LIST.get(f"{lv}_{rare}_{ev}_{fu}") or [0.375, 0.375, 100, 100, 0.0, 0.0]


def get_fusion_max(it):
    info = ITEMS.get(str(it.get("_itemDataId", ""))) or {}
    lv = int(info.get("lv", 1))
    rare = int(info.get("r", 0))
    ev = int(it.get("_evolutionLevel", 0) or 0)
    return int(FUSION_MAX.get(f"{lv}_{rare}_{ev}", 5))


def item_fusion_xp_output(it):
    """Matches UIFusion.UpdateFusionInfo per-material XP: RoundToInt(_outputXp * _defaultXp)."""
    if not isinstance(it, dict):
        return 0
    info = ITEMS.get(str(it.get("_itemDataId", ""))) or {}
    dxp = float(info.get("dxp", 1.0))
    fd = get_fusion_data(it)
    return int(round(float(fd[3]) * dxp))


def apply_fusion(it, xp_sum):
    """Advances _fusionXp and _fusionLevel using UIFusion.GetLevelUp's exact rules; returns need_sc."""
    info = ITEMS.get(str(it.get("_itemDataId", ""))) or {}
    part = str(info.get("p", 0))
    factor = float(FUSION_CONFIG.get(part, 1.0))
    fd = get_fusion_data(it)
    need_sc = int(float(xp_sum) * float(fd[0]) * factor)
    max_lv = get_fusion_max(it)

    rem_xp = int(xp_sum)
    cur_xp = int(it.get("_fusionXp", 0) or 0)
    cur_lv = int(it.get("_fusionLevel", 0) or 0)
    need_xp = int(fd[2])

    while rem_xp > 0:
        if need_xp <= 0 or cur_lv >= max_lv:
            cur_xp = max(0, need_xp)
            break
        step = min(rem_xp, need_xp - cur_xp)
        if step <= 0:
            step = rem_xp
        rem_xp -= step
        cur_xp += step
        if cur_xp >= need_xp:
            if cur_lv < max_lv:
                cur_xp -= need_xp
                cur_lv += 1
                fd = get_fusion_data(it, fusion_lv=cur_lv)
                need_xp = int(fd[2])
            else:
                cur_xp = need_xp
                break

    it["_fusionLevel"] = cur_lv
    it["_fusionXp"] = cur_xp
    return need_sc


def item_score(it):
    """Computes ItemInventory.GetScore() from _equipAttList and fusion/evolution tables."""
    item_id = it.get("_itemDataId", "")
    if stackable(item_id):
        return 0
    att_obj = it.get("_equipAttList")
    if not isinstance(att_obj, dict) or not att_obj.get("_list"):
        att_obj = equip_att_list(item_id)
    info = ITEMS.get(str(item_id)) or {}
    lv = int(info.get("lv", 1))
    rare = int(info.get("r", 0))
    fusion_lv = int(it.get("_fusionLevel", 0) or 0)
    evol_lv = int(it.get("_evolutionLevel", 0) or 0)

    total_eff = 0.0
    total_cd = 0.0
    for ev_i in range(evol_lv):
        max_f = int(FUSION_MAX.get(f"{lv}_{rare}_{ev_i}", 5))
        for fu_i in range(1, max_f + 1):
            row = FUSION_LIST.get(f"{lv}_{rare}_{ev_i}_{fu_i}")
            if row:
                total_eff += float(row[4])
                total_cd += float(row[5])
    for fu_j in range(1, fusion_lv + 1):
        row = FUSION_LIST.get(f"{lv}_{rare}_{evol_lv}_{fu_j}")
        if row:
            total_eff += float(row[4])
            total_cd += float(row[5])
    for ev_k in range(1, evol_lv + 1):
        erow = EVOLUTION_LIST.get(f"{lv}_{rare}_{ev_k}")
        if erow:
            total_eff += float(erow[0])
            total_cd += float(erow[1])

    total = 0.0
    for att in att_obj.get("_list", []):
        param = att.get("HitParames", "")
        val = float(att.get("HitValues", 0.0) or 0.0)
        if int(att.get("IsNature", 1) or 0) != 0:
            if param == "CRITICAL_STRIKE_DAMAGE":
                val += total_cd
            else:
                val *= (1.0 + total_eff)
        mult = float(ATTR_VALUES.get(param, 1.0))
        if val > 0.0:
            total += max(1.0, val * mult)
    return int(math.floor(total))


def new_item(pos, item_id, amount, new=True, **extra):
    it = {"_inventoryPos": pos, "_itemDataId": item_id, "_amount": amount, "_isNew": 1 if new else 0,
          "_fusionLevel": 0, "_evolutionLevel": 0, "_fusionXp": 0}
    if not stackable(item_id):
        it["_socketState"] = 0
        it["_runeItemId"] = ""
        it["_equipAttList"] = equip_att_list(item_id)
    it.update(extra)
    return it


def add_item(inv, item_id, amount=1, pl=None):
    """Adds to the inventory as PlayerInventory.AddItemInventory does; routes token_* to <role>_token."""
    if is_token(item_id):
        if pl is not None:
            pl.add_token(item_id, amount)
        return []
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
