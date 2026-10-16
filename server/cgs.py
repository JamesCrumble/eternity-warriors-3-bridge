"""Custom Game Server: the game logic Glu ran server-side (Utils.CustomGameServerMessage).

The client sends a JSON string with "messageType" (and usually "op_type"); the
answer is a JSON string too. A failure carries {"errorCode": ...}.
Handlers are added as the client's requests show what each answer must hold;
anything else answers {} with SUCCESS and lands in the log.
"""
import json
import time

log_entries = []
LOG_MAX = 500


def log(msg):
    print("[cgs] " + msg, flush=True)


HANDLERS = {}


def handler(message_type):
    def wrap(fn):
        HANDLERS[message_type] = fn
        return fn
    return wrap


def handle(store, pid, cgs_id, payload):
    try:
        msg = json.loads(payload) if isinstance(payload, str) else (payload or {})
    except ValueError:
        msg = {}
    mtype = msg.get("messageType", "?")
    op = msg.get("op_type", "")
    fn = HANDLERS.get(mtype)
    if fn:
        status, answer = fn(store, pid, msg)
        log("%s/%s -> %s %s" % (mtype, op, "ok" if status else "error", json.dumps(answer)[:160]))
    else:
        status, answer = True, {}
        log("unhandled %s/%s %s" % (mtype, op, json.dumps(msg)[:300]))
    log_entries.append({"t": time.time(), "player": pid, "type": mtype, "op": op, "request": msg,
                        "ok": status, "answer": answer})
    del log_entries[:-LOG_MAX]
    return status, json.dumps(answer)


@handler("heartbeat")
def heartbeat(store, pid, msg):
    return True, {"time": int(time.time())}


# The attributes a fresh account gets. The client builds its full default profile
# itself (PlayerInfoManager.CreateDefaultProfiles) and only overlays what the server
# returns, then saves everything with SetAttributes; the server's part was the few
# fields it owns. Values are strings: the client reads them with value.ToString().
NEW_ACCOUNT = {
    "save_version": "4.1.0",
    "hackflag2": "0",
    "cheat_flag": "0",
    "hc_current": "5",
}


# Each hero's starting gear. Glu's server wrote it with the account (the client's own
# PlayerInfoManager.CreateDefaultProfiles is never called in 4.1.0); without it the hero
# has nothing equipped: no weapon (attacks do no damage, vases stay whole), no armour
# (the composited body texture stays black). The ids, the order and the counts are the
# InitInformation asset's _defaultEquipment_* and _defaultItems_* lists
# (base_uniform_global_manager bundle).
STARTER = {
    "mage": (["mage_weapon_0_white_initial", "mage_helm_0_white_initial", "mage_belt_0_white_initial",
              "mage_armpiece_0_white_initial", "mage_leggings_0_white_initial", "mage_shoulder_0_white_initial"],
             [("mage_weapon_1_green_tutorial", 1), ("potion_hp", 3), ("potion_mp", 2)]),
    "warrior": (["warrior_weapon_0_white_initial", "warrior_armpiece_0_white_initial",
                 "warrior_belt_0_white_initial", "warrior_helm_0_white_initial",
                 "warrior_leggings_0_white_initial", "warrior_shoulder_0_white_initial"],
                [("warrior_weapon_1_green_tutorial", 1), ("potion_hp", 3), ("potion_mp", 2)]),
    "monk": (["monk_weapon_0_white_initial", "monk_armpiece_0_white_initial", "monk_belt_0_white_initial",
              "monk_helm_0_white_initial", "monk_leggings_0_white_initial", "monk_shoulder_0_white_initial"],
             [("monk_weapon_1_green_tutorial", 1), ("potion_hp", 3), ("potion_mp", 2)]),
}
STACKABLE = ("potion_",)
CURRENT_ROLE = "warrior"   # role_current = 1, the hero a new account starts with


def starter_attributes(role):
    """<role>_inventory and <role>_equipment as PlayerInventory.SaveToHashtable writes them."""
    equipment, items = STARTER[role]
    inv, worn = [], []

    def add(item_id, amount, new):
        if item_id.startswith(STACKABLE):
            for it in inv:
                if it["_itemDataId"] == item_id:
                    it["_amount"] += amount
                    return it["_inventoryPos"]
        pos = len(inv)
        inv.append({"_inventoryPos": pos, "_itemDataId": item_id, "_amount": amount, "_isNew": 1 if new else 0,
                    "_fusionLevel": 0, "_evolutionLevel": 0, "_fusionXp": 0})
        return pos

    for item_id in equipment:
        worn.append(add(item_id, 1, False))
    for item_id, count in items:
        add(item_id, count, True)
    attrs = {role + "_inventory": json.dumps({"_incrementId": len(inv), "_inventory": inv}),
             role + "_equipment": json.dumps(worn)}
    if role == CURRENT_ROLE:
        # PlayerProfile.SavePlayerProfileCommonJson's fields. "_used" marks the hero as played:
        # AccountProfile.LastUsedRole is -1 while no hero is, and the character screen then
        # takes its three-hero path, which trips over BackKeyManager under this runtime.
        attrs[role + "_basic"] = json.dumps({
            "_currentXp": 0, "_currentXpPrecent": 0, "_currentLevel": 1, "_upgradeWeaponTimes": 0,
            "_playMultiplayerTimes": 0, "_upgradeSkillTimes": 0, "_maxCombo": 0, "_honour": 0, "_used": True,
            "_difficultyLevel": 0, "_giftState": 0, "_giftRemainingTime": 0, "_usedSkill": [], "_requestGuilds": [],
            "_gachaFreeCount": [], "_levelState": [], "_levelStateHard": [], "_levelStateLegendary": [],
            "_tutorialState": [], "_playhavenCounter": []})
    return attrs


def ensure_starter_profile(store, pid):
    """Gives every hero of the account its starting gear unless it already has an inventory."""
    p = store.get(pid)
    if p is None:
        return
    missing = []
    for role in STARTER:
        have = p["attributes"]
        missing += [{"name": k, "value": v} for k, v in starter_attributes(role).items() if k not in have]
    if missing:
        store.set_attributes(pid, missing)
        log("starter gear written for %s (%d attributes)" % (pid[:8], len(missing)))


@handler("account_profile")
def account_profile(store, pid, msg):
    if msg.get("op_type") == "CreateDefault":
        p = store.get(pid)
        if p is not None and not p["attributes"]:
            store.set_attributes(pid, [{"name": k, "value": v} for k, v in NEW_ACCOUNT.items()])
        ensure_starter_profile(store, pid)
        nick = (p or {}).get("nickName") or ("Hero" + pid[:4])
        if p is not None and not p.get("nickName"):
            p["nickName"] = nick
            store.save()
        return True, nick          # the client strips the quotes and takes it as the nickname
    log("account_profile/%s not implemented: %s" % (msg.get("op_type"), json.dumps(msg)[:200]))
    return True, {}


@handler("check_version")
def check_version(store, pid, msg):
    return True, {}            # no "blocktime": not banned


# ---- what the character-select screen asks for right after login ----------------
# Each of these is a blocking request in the client's ConnectManager queue: an
# answer its parser cannot read throws inside the callback, the ACK never comes,
# and the queue (and the "Accessing Network" overlay) stays stuck.


# ---- the rest of the game, one module per area (each registers its handlers) ------------
import cgs_battle   # noqa: E402,F401  battles, tower, raid boss, PvP
import cgs_events   # noqa: E402,F401  bonuses, events, IAP, social, quests
import cgs_items    # noqa: E402,F401  store, selling, skills, fusion, evolution, runes, gacha
