"""CGS: battles - campaign levels, the endless tower, raid bosses, PvP.

Campaign battles are fully served: the client reports what it earned
(BattleSummary.sendBattleSummary: exp, money, loot, potions used) and the
server, which owns the money, experience and inventory, books it and sends
the new totals back. The tower needs wave data generated server-side and the
raid boss and PvP modes need live events and other players; until those
exist they answer "not available" instead of leaving the client waiting.
"""
import json
import time

from cgs import handler, log
import cgs_state as st

# cost_items keys (BattleSummary.GetCombatCostHashtable) -> the potion each one used up.
POTIONS = {"hp": "potion_hp", "mp": "potion_mp"}
NOT_AVAILABLE = "99999"


def token(pid):
    return "%s-%d" % (pid[:8], int(time.time() * 1000))


@handler("battle")
def battle(store, pid, msg):
    op = msg.get("op_type")
    if op == "battle_enter":
        # EnergyManager.ProcessGetLevelEnergyInfo. Without "Normal"/"Hard" the level costs no energy
        # and UIEnterLevel shows its plain start button; with them it looks up an energy counter of
        # that type, finds none, throws, and the waiting screen never closes.
        return True, {"level_id": msg.get("level_id", "")}
    if op == "battle_start":
        # LevelManager.OnSendBeginBattle: "items"/"skill" are checked against the client's own
        # equipment (empty lists always pass); without "enemyData" the level's own enemies are used.
        return True, {"items": [], "skill": [], "token": token(pid)}
    if op == "battle_end":
        return battle_end(store, pid, msg)
    if op == "battle_log":
        return True, {}             # telemetry; "cheat_record" > 0 would quit the game
    log("battle/%s not implemented: %s" % (op, json.dumps(msg)[:300]))
    return True, {}


def battle_end(store, pid, msg):
    """BattleSummary.OnSendBattleSummary reads sc, sc_current and the common reward fields."""
    data = st.payload_json(msg)
    pl = st.Player(store, pid)
    inv = pl.inventory()
    touched = []

    pl.xp = pl.xp + int(data.get("exp", 0) or 0)
    money = 0
    loot = data.get("items") or {}
    if data.get("pass"):
        money = int(loot.get("money", 0) or 0)
        for item_id, count in loot.items():
            if item_id != "money" and int(count) > 0:
                touched += st.add_item(inv, item_id, int(count))
    pl.sc = pl.sc + money

    cost = data.get("cost_items") or {}
    for key, potion in POTIONS.items():
        if int(cost.get(key, 0) or 0) > 0:
            touched += st.take_item(inv, potion, int(cost[key]))
    hc_cost = int(cost.get("hc", 0) or 0)
    pl.hc = pl.hc - hc_cost
    pl.save_inventory(inv)
    pl.save()

    log("battle_end %s pass=%s: +%d xp, +%d sc, %d item(s)" % (
        data.get("level_id"), data.get("pass", 0), int(data.get("exp", 0) or 0), money, len(touched)))
    # ParseCommonReward subtracts BattleSummary.HcCost from hc_current itself during a battle.
    return True, {"sc": money, "sc_current": pl.sc, "hc_current": pl.hc + hc_cost, "exp": pl.xp,
                  "items": touched}


@handler("detect")
def detect(store, pid, msg):
    return True, {}                 # anti-cheat probe; "cheat_record" > 0 would quit the game


# ---- the endless tower --------------------------------------------------------------

@handler("tower")
def tower(store, pid, msg):
    op = msg.get("op_type")
    if op == "tower_enter":
        # TowerManager.ProcessEnterTowerMessage: no towers yet (each needs server-made waves).
        return True, {"energy": 10, "max_energy": 10, "energy_price": 10, "towers": {}, "friend_data": {}}
    log("tower/%s not available yet" % op)
    return st.error(NOT_AVAILABLE)


# ---- raid boss events ---------------------------------------------------------------

@handler("raidboss")
def raidboss(store, pid, msg):
    op = msg.get("op_type")
    if op == "get_status":
        # RaidBossEventManager.OnResponseEventState: no event running, so the town shows none.
        return True, {"current_event": False}
    log("raidboss/%s: no event running" % op)
    return st.error(NOT_AVAILABLE)


# ---- player versus player -------------------------------------------------------------

@handler("pvp")
def pvp(store, pid, msg):
    log("pvp/%s: no other players on this server" % msg.get("op_type"))
    return st.error(NOT_AVAILABLE)


@handler("player")
def player(store, pid, msg):
    # UIPvpCGS.OnSendCheckBaseInfo, before PvP matchmaking.
    return st.error(NOT_AVAILABLE)
