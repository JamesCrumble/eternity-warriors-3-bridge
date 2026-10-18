"""Custom Game Server: the game logic Glu ran server-side (Utils.CustomGameServerMessage).

The client sends a JSON string with "messageType" (and usually "op_type"); the
answer is a JSON string too. A failure carries {"errorCode": ...}.
Handlers are added as the client's requests show what each answer must hold;
anything else answers {} with SUCCESS and lands in the log.
"""
import json
import time

import cgs_state as st

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
STARTER_SKILLS = {
    "mage": ["FireSpear", "Parry", "LightningBall"],
    "warrior": ["Dash", "Parry", "Bash"],
    "monk": ["SevenPunch", "Dodge", "Vortex"],
}
# Since "_used": True skips the village intro tutorial, pre-complete the village combat
# tutorial keys ("move", "attack", "kill", "skill1", "skill2") so HUDSkillHandler.InitTutorialEffect
# activates all skill buttons (especially _skillIcons[1] = Dash / FireSpear / SevenPunch).
STARTER_TUTORIAL_STEPS = [
    ["move", 2],
    ["attack", 2],
    ["kill", 2],
    ["skill1", 2],
    ["skill2", 2],
    ["starter_51", 2],
    ["skill_50", 2],
]
STACKABLE = ("potion_",)
CURRENT_ROLE = "warrior"   # role_current = 1, the hero a new account starts with


def starter_attributes(role):
    """<role>_inventory, <role>_equipment, <role>_skill, <role>_token, and <role>_basic."""
    equipment, items = STARTER[role]
    skills = STARTER_SKILLS[role]
    inv, worn = [], []

    def add(item_id, amount, new):
        if item_id.startswith(STACKABLE):
            for it in inv:
                if it["_itemDataId"] == item_id:
                    it["_amount"] += amount
                    return it["_inventoryPos"]
        pos = len(inv)
        inv.append(st.new_item(pos, item_id, amount, new=new))
        return pos

    for item_id in equipment:
        worn.append(add(item_id, 1, False))
    for item_id, count in items:
        add(item_id, count, True)
    attrs = {
        role + "_inventory": json.dumps({"_incrementId": len(inv), "_inventory": inv}),
        role + "_equipment": json.dumps(worn),
        role + "_skill": json.dumps([[s, 1] for s in skills]),
        role + "_token": json.dumps({}),
        # PlayerProfile.SavePlayerProfileCommonJson's fields. "_used" marks the hero as played:
        # AccountProfile.LastUsedRole is -1 while no hero is, and the character screen then
        # takes its three-hero path, which trips over BackKeyManager under this runtime.
        # Since "_used": True skips the village1 intro tutorial that teaches/equips starting
        # skills, we pre-populate _usedSkill and _tutorialState so combat skills work immediately.
        role + "_basic": json.dumps({
            "_currentXp": 0, "_currentXpPrecent": 0, "_currentLevel": 1, "_upgradeWeaponTimes": 0,
            "_playMultiplayerTimes": 0, "_upgradeSkillTimes": 0, "_maxCombo": 0, "_honour": 0,
            "_used": (role == CURRENT_ROLE), "_difficultyLevel": 0, "_giftState": 0, "_giftRemainingTime": 0,
            "_usedSkill": list(skills), "_requestGuilds": [], "_gachaFreeCount": [],
            "_levelState": [], "_levelStateHard": [], "_levelStateLegendary": [],
            "_tutorialState": [list(x) for x in STARTER_TUTORIAL_STEPS], "_playhavenCounter": []}),
    }
    return attrs


def ensure_starter_profile(store, pid):
    """Gives every hero of the account its starting gear, attributes, tokens, GS and skills."""
    p = store.get(pid)
    if p is None:
        return
    have = p["attributes"]
    updates = []
    for role in STARTER:
        skills = STARTER_SKILLS[role]
        for k, v in starter_attributes(role).items():
            if k not in have:
                updates.append({"name": k, "value": v})
        skill_key = role + "_skill"
        if skill_key in have:
            try:
                cur_skills = json.loads(have[skill_key]) if isinstance(have[skill_key], str) else have[skill_key]
            except (ValueError, TypeError):
                cur_skills = []
            if not cur_skills:
                updates.append({"name": skill_key, "value": json.dumps([[s, 1] for s in skills])})
        basic_key = role + "_basic"
        if basic_key in have:
            try:
                basic = json.loads(have[basic_key]) if isinstance(have[basic_key], str) else dict(have[basic_key])
            except (ValueError, TypeError):
                basic = None
            if isinstance(basic, dict):
                changed = False
                used_sk = basic.get("_usedSkill")
                if not isinstance(used_sk, list) or not any(used_sk):
                    basic["_usedSkill"] = list(skills)
                    changed = True
                elif not used_sk[0]:
                    used_sk[0] = skills[0]
                    basic["_usedSkill"] = used_sk
                    changed = True
                tut_list = basic.get("_tutorialState")
                if not isinstance(tut_list, list):
                    tut_list = []
                tut_map = { entry[0]: entry[1] for entry in tut_list if isinstance(entry, list) and len(entry) >= 2 }
                tut_changed = False
                for tk, tv in STARTER_TUTORIAL_STEPS:
                    if tut_map.get(tk) != tv:
                        tut_map[tk] = tv
                        tut_changed = True
                if tut_changed or not tut_list:
                    basic["_tutorialState"] = [[k, v] for k, v in tut_map.items()]
                    changed = True
                if changed:
                    updates.append({"name": basic_key, "value": json.dumps(basic)})

        # Repair <role>_inventory: populate missing _equipAttList on equipment and migrate token_* to <role>_token
        inv_key = role + "_inventory"
        tok_key = role + "_token"
        if inv_key in have:
            try:
                inv_obj = json.loads(have[inv_key]) if isinstance(have[inv_key], str) else dict(have[inv_key])
            except (ValueError, TypeError):
                inv_obj = None
            if isinstance(inv_obj, dict) and isinstance(inv_obj.get("_inventory"), list):
                try:
                    tok_obj = json.loads(have.get(tok_key) or "{}")
                    if not isinstance(tok_obj, dict):
                        tok_obj = {}
                except (ValueError, TypeError):
                    tok_obj = {}
                inv_changed = False
                tok_changed = False
                kept_items = []
                for it in inv_obj["_inventory"]:
                    iid = str(it.get("_itemDataId", ""))
                    if st.is_token(iid):
                        cnt = int(it.get("_amount", 1) or 1)
                        tok_obj[iid] = int(tok_obj.get(iid, 0) or 0) + cnt
                        inv_changed = True
                        tok_changed = True
                        continue
                    if not st.stackable(iid):
                        att = it.get("_equipAttList")
                        if not isinstance(att, dict) or not att.get("_list"):
                            it["_equipAttList"] = st.equip_att_list(iid)
                            it.setdefault("_socketState", 0)
                            it.setdefault("_runeItemId", "")
                            inv_changed = True
                    kept_items.append(it)
                if inv_changed:
                    inv_obj["_inventory"] = kept_items
                    updates.append({"name": inv_key, "value": json.dumps(inv_obj)})
                if tok_changed or tok_key not in have:
                    updates.append({"name": tok_key, "value": json.dumps(tok_obj)})

    if "property" in have and isinstance(have["property"], str):
        try:
            prop = json.loads(have["property"])
        except (ValueError, TypeError):
            prop = None
        if isinstance(prop, dict):
            prop_changed = False
            for idx, rname in (("0", "mage"), ("1", "warrior"), ("2", "monk")):
                rprop = prop.get(idx)
                if isinstance(rprop, dict):
                    if not rprop.get("_skillState"):
                        rprop["_skillState"] = [[s, 1] for s in STARTER_SKILLS[rname]]
                        prop_changed = True
                    eq_inv = rprop.get("_equipedInventory")
                    if isinstance(eq_inv, dict) and isinstance(eq_inv.get("_inventory"), list):
                        for it in eq_inv["_inventory"]:
                            iid = str(it.get("_itemDataId", ""))
                            if not st.stackable(iid):
                                att = it.get("_equipAttList")
                                if not isinstance(att, dict) or not att.get("_list"):
                                    it["_equipAttList"] = st.equip_att_list(iid)
                                    prop_changed = True
            if prop_changed:
                updates.append({"name": "property", "value": json.dumps(prop)})
    if updates:
        store.set_attributes(pid, updates)
        log("starter gear/skills written for %s (%d attributes)" % (pid[:8], len(updates)))
    # Ensure gearscore attribute is up to date with equipped items
    pl = st.Player(store, pid)
    pl.update_gs()
    pl.save()


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
