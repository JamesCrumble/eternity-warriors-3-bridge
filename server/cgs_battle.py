"""CGS: battles - campaign levels, the endless tower, raid bosses, PvP.

Campaign battles are fully served:
  - battle_start receives the level's enemyIds (enemies, chests, crates/vases,
    and bosses) and returns enemyData (EndlessWave format) with XP, stats, and
    rolled loot tables from the game's LootDatabase1..Bonus3.
  - battle_end receives what the player collected (BattleSummary.sendBattleSummary:
    exp, money, loot, potions used), books it into the player's authoritative
    inventory/currencies/tokens/GS, and returns the updated totals.
"""
import json
import random
import time

from cgs import handler, log
import cgs_state as st

# cost_items keys (BattleSummary.GetCombatCostHashtable) -> the potion each one used up.
POTIONS = {"hp": "potion_hp", "mp": "potion_mp"}
NOT_AVAILABLE = "99999"

_DEFAULT_ATTRS = [4.0, 100, 15.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1]


def token(pid):
    return "%s-%d" % (pid[:8], int(time.time() * 1000))


def _weighted_pick(entries):
    if not entries:
        return None
    total = sum(e[0] for e in entries)
    if total <= 0:
        return random.choice(entries)
    r = random.randint(1, total)
    acc = 0
    for e in entries:
        acc += e[0]
        if r <= acc:
            return e
    return entries[-1]


def _roll_instance_loot(eid, role_idx):
    elower = eid.lower()
    is_chest = any(k in elower for k in ("treasure", "box", "chest", "vase", "barrel"))
    is_boss = ("_b_" in elower or "_mb_" in elower or "boss" in elower) and not is_chest
    is_elite = ("_el_" in elower or "elite" in elower) and not is_chest

    pool1 = st.LOOT1.get(eid) or st.LOOT2.get(eid) or st.LOOT1.get("treasure_VE_Lv1") or []
    pool_b1 = st.LOOT_B1.get(eid) or []
    pool_b3 = st.LOOT_B3.get(eid) or []

    money_entry = None
    role_items = []
    for entry in pool1:
        w, iid, cmin, cmax = entry
        if iid == "money":
            money_entry = entry
        elif "tutorial" not in iid:
            info = st.ITEMS.get(iid)
            if info is None or info.get("c", 9) not in (0, 1, 2) or info.get("c") == role_idx:
                role_items.append(entry)

    drops = {}

    def add_drop(iid, cnt):
        if cnt > 0:
            drops[iid] = drops.get(iid, 0) + cnt

    def roll_money(mult=1.0, min_floor=5):
        if money_entry:
            _, _, cmin, cmax = money_entry
            lo = max(min_floor, int(cmin * mult))
            hi = max(lo, int(cmax * mult))
            add_drop("money", random.randint(lo, hi))
        else:
            add_drop("money", random.randint(10, 35))

    def roll_item(entries):
        picked = _weighted_pick(entries)
        if picked:
            _, iid, cmin, cmax = picked
            add_drop(iid, random.randint(max(1, cmin), max(1, cmax)))

    if is_boss:
        roll_money(mult=2.5, min_floor=40)
        for _ in range(2):
            roll_item(role_items)
        if pool_b1:
            roll_item(pool_b1)
        if pool_b3 and random.random() < 0.25:
            roll_item(pool_b3)
    elif is_chest:
        is_big_chest = any(k in elower for k in ("_mb_", "_el_", "_b_", "large"))
        if is_big_chest:
            roll_money(mult=1.8, min_floor=25)
            roll_item(role_items)
            if pool_b1 and random.random() < 0.65:
                roll_item(pool_b1)
        else:
            roll_money(mult=1.2, min_floor=10)
            if random.random() < 0.55:
                roll_item(role_items)
            elif pool_b1 and random.random() < 0.35:
                roll_item(pool_b1)
    elif is_elite:
        if random.random() < 0.90:
            roll_money(mult=1.5, min_floor=15)
        if random.random() < 0.55:
            roll_item(role_items)
        if pool_b1 and random.random() < 0.45:
            roll_item(pool_b1)
    else:
        if random.random() < 0.65:
            roll_money(mult=1.0, min_floor=5)
        if random.random() < 0.18:
            roll_item(role_items)

    return drops


def build_enemy_data(store, pid, msg):
    data = st.payload_json(msg)
    enemy_ids = data.get("enemyIds") or {}
    if not isinstance(enemy_ids, dict) or not enemy_ids:
        return None
    pl = st.Player(store, pid)
    role_idx = st.ROLES.index(pl.role)
    entries = []
    for eid, count in enemy_ids.items():
        cnt = max(1, int(count or 1))
        einfo = st.ENEMIES.get(str(eid))
        if einfo:
            xp = int(einfo.get("xp", 10))
            vp = int(einfo.get("vp", 0))
            attrs = list(einfo.get("a") or _DEFAULT_ATTRS)
        else:
            xp, vp, attrs = 15, 0, list(_DEFAULT_ATTRS)
        loot_instances = [_roll_instance_loot(str(eid), role_idx) for _ in range(cnt)]
        entries.append([str(eid), cnt, xp, vp, attrs, loot_instances])
    return [0, 0, entries, 0]


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
        # equipment (empty lists always pass); "enemyData" populates AcData._lootXp and _lootItems
        # for every enemy, chest, crate/vase, and boss in the level.
        ans = {"items": [], "skill": [], "token": token(pid)}
        edata = build_enemy_data(store, pid, msg)
        if edata is not None:
            ans["enemyData"] = edata
        return True, ans
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
                touched += st.add_item(inv, item_id, int(count), pl=pl)
    pl.sc = pl.sc + money

    cost = data.get("cost_items") or {}
    for key, potion in POTIONS.items():
        if int(cost.get(key, 0) or 0) > 0:
            touched += st.take_item(inv, potion, int(cost[key]))
    hc_cost = int(cost.get("hc", 0) or 0)
    pl.hc = pl.hc - hc_cost
    pl.save_inventory(inv)
    gs = pl.update_gs()
    pl.save()

    log("battle_end %s pass=%s: +%d xp, +%d sc, %d item(s)" % (
        data.get("level_id"), data.get("pass", 0), int(data.get("exp", 0) or 0), money, len(touched)))
    # ParseCommonReward subtracts BattleSummary.HcCost from hc_current itself during a battle.
    return True, {"sc": money, "sc_current": pl.sc, "hc_current": pl.hc + hc_cost, "exp": pl.xp,
                  "gs": gs, "token": pl.tokens(), "items": touched}


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
