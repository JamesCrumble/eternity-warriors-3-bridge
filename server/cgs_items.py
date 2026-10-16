"""CGS: store, selling, skills, fusion, evolution, runes, gacha, guilds, mail.

Prices, gacha pools and upgrade costs live in the game's data bundles; until
the server reads them, what needs them answers "not available" (a message box,
never a hang). Skills upgrade for free; the mage unlocks for free.
"""
import json

from cgs import handler, log
import cgs_state as st

NOT_AVAILABLE = 99999


@handler("store")
def store_msg(store, pid, msg):
    op = msg.get("op_type")
    pl = st.Player(store, pid)
    if op == "get_unlock_mage_price":
        return True, {"price": 0}           # 0 hides the unlock button; the mage is unlocked below
    if op == "unlock_mage":
        pl.set("mage_unlock", 1)
        pl.save()
        return True, {"hc_current": pl.hc}
    log("store/%s needs the store data (not loaded yet): %s" % (op, json.dumps(msg)[:200]))
    return st.error(NOT_AVAILABLE)


@handler("skill")
def skill(store, pid, msg):
    # UISkillsHandler.OnLearnOrUpgradeSkillResponse; the level is kept in <role>_skill
    # as [[name, level], ...] (AccountProfile.FillDictionary).
    if msg.get("op_type") != "upgrade":
        return st.error(NOT_AVAILABLE)
    pl = st.Player(store, pid)
    name = msg.get("skill_name", "")
    try:
        levels = dict(json.loads(pl.get(pl.role + "_skill") or "[]"))
    except (ValueError, TypeError):
        levels = {}
    levels[name] = int(levels.get(name, 0)) + 1
    pl.set(pl.role + "_skill", json.dumps([[k, v] for k, v in levels.items()]))
    pl.save()
    return True, {"skill_name": name, "money_type": msg.get("money_type", "sc"), "currency_num": 0}


@handler("gacha")
def gacha(store, pid, msg):
    if msg.get("op_type") == "get_event":
        return True, {}                     # GachaEventManager: no gacha event running
    log("gacha/%s needs the gacha data (not loaded yet)" % msg.get("op_type"))
    return st.error(NOT_AVAILABLE)


@handler("guild")
def guild(store, pid, msg):
    return st.error(NOT_AVAILABLE)          # no other players on this server


@handler("mail_server")
def mail_server(store, pid, msg):
    if msg.get("op_type") == "receive_mail":
        return True, {}                     # no gift mail
    return st.error(NOT_AVAILABLE)


@handler("change_nickname")
def change_nickname(store, pid, msg):
    return st.error(NOT_AVAILABLE)


for _area in ("fusion", "evolution", "rune_socket"):
    @handler(_area)
    def _needs_data(store, pid, msg, _area=_area):
        log("%s/%s needs the item data (not loaded yet)" % (_area, msg.get("op_type")))
        return st.error(NOT_AVAILABLE)
