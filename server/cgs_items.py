"""CGS: store, selling, skills, fusion, evolution, runes, gacha, guilds, mail.

Prices, gacha pools and upgrade costs live in the game's data bundles; gacha
and equipment attributes/scores are served from server/generated/game_data.json.
Skills upgrade for free; the mage unlocks for free.
"""
import json
import random

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
    if op == "sell":
        # UIInventory.SendSellRequest sends equipment_position_list, new_item_list, and sell_position_list
        # whenever the inventory/equipment screen closes after equipping/unequipping/viewing/selling items.
        inv = pl.inventory()
        if "equipment_position_list" in msg and isinstance(msg["equipment_position_list"], list):
            eq_pos = [int(p) for p in msg["equipment_position_list"]]
            pl.set(pl.role + "_equipment", json.dumps(eq_pos))
        for pos in msg.get("new_item_list") or []:
            it = st.item_at(inv, int(pos))
            if it is not None:
                it["_isNew"] = 0
        sell_pos = [int(p) for p in (msg.get("sell_position_list") or [])]
        money_loot = sum(st.item_sell_value(st.item_at(inv, p)) for p in sell_pos) if sell_pos else 0
        if sell_pos:
            st.take_positions(inv, sell_pos)
        if money_loot > 0:
            pl.sc = pl.sc + money_loot
        pl.save_inventory(inv)
        gs = pl.update_gs()
        pl.save()
        return True, dict(st.currencies(pl), money_loot=money_loot, gs=gs, items=[])
    if op in ("buy", "buy_gift", "do_tutorial"):
        inv = pl.inventory()
        touched = []
        if msg.get("id"):
            touched += st.add_item(inv, str(msg["id"]), int(msg.get("amount", 1)), pl=pl)
        if isinstance(msg.get("item_list"), dict):
            for item_id, cnt in msg["item_list"].items():
                touched += st.add_item(inv, str(item_id), int(cnt), pl=pl)
        pl.save_inventory(inv)
        gs = pl.update_gs()
        pl.save()
        return True, dict(st.currencies(pl), gs=gs, token=pl.tokens(), items=touched)
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


def _build_gacha_pool(gcfg, role_idx):
    chase = gcfg.get("chase", "")
    hit = gcfg.get("hit", "0")
    token_id = gcfg.get("c1_id", "token_wood")
    tier = chase.split("_")[0] if chase.startswith("t") and "_" in chase else ""

    group_names = []
    if chase:
        group_names.append(chase)
    if hit and hit != "0":
        group_names.append(hit)
    if tier:
        if "wood" in token_id:
            group_names.extend([f"{tier}_white", f"{tier}_green", f"{tier}_blue"])
        elif "iron" in token_id:
            group_names.extend([f"{tier}_green", f"{tier}_blue", f"{tier}_purple"])
        else:
            group_names.extend([f"{tier}_blue", f"{tier}_purple", f"{tier}_gold"])

    pool = []
    seen = set()
    for gname in group_names:
        for iid, weight, cnt in st.GACHA_GROUPS.get(gname) or []:
            if iid in seen:
                continue
            info = st.ITEMS.get(iid)
            if info is not None and info.get("c", 9) in (0, 1, 2) and info.get("c") != role_idx:
                continue
            seen.add(iid)
            pool.append((iid, max(1, int(weight)), max(1, int(cnt))))
    if not pool:
        pool = [("potion_hp", 10, 2), ("potion_mp", 10, 2)]
    return pool


@handler("gacha")
def gacha(store, pid, msg):
    op = msg.get("op_type")
    if op == "get_event":
        return True, {}                     # GachaEventManager: no gacha event running

    gacha_id = str(msg.get("gacha_id", "150"))
    count = max(1, int(msg.get("count", 1) or 1))
    gtype = int(msg.get("gacha_type", 2) or 2)  # 2 = TYPE_TOKEN, 4 = TYPE_HC, 3 = TYPE_SC

    pl = st.Player(store, pid)
    role_idx = st.ROLES.index(pl.role)
    gcfg = st.GACHA_ITEMS.get(gacha_id) or st.GACHA_ITEMS.get("150") or {}

    tok_id = gcfg.get("c10_id" if count >= 10 else "c1_id") or "token_wood"
    tok_cost = int(gcfg.get("c10_cnt" if count >= 10 else "c1_cnt") or count)
    hc_cost = int(gcfg.get("c10_hc" if count >= 10 else "c1_hc") or 0)
    sc_cost = int(gcfg.get("c10_sc" if count >= 10 else "c1_sc") or 0)

    tok = pl.tokens()
    if gtype == 2 or tok.get(tok_id, 0) >= tok_cost:
        tok[tok_id] = max(0, int(tok.get(tok_id, 0)) - tok_cost)
        pl.save_tokens(tok)
    elif gtype == 4 and hc_cost > 0:
        pl.hc = max(0, pl.hc - hc_cost)
    elif sc_cost > 0:
        pl.sc = max(0, pl.sc - sc_cost)

    # Prefer items directly in the chase group so 1x spin lands cleanly on a visible wheel slot
    chase_name = gcfg.get("chase", "")
    chase_pool = []
    for iid, w, cnt in st.GACHA_GROUPS.get(chase_name) or []:
        info = st.ITEMS.get(iid)
        if info is None or info.get("c", 9) not in (0, 1, 2) or info.get("c") == role_idx:
            chase_pool.append((iid, max(1, int(w)), max(1, int(cnt))))
    full_pool = _build_gacha_pool(gcfg, role_idx)
    active_pool = chase_pool if (count == 1 and chase_pool) else full_pool

    inv = pl.inventory()
    touched = []
    result = []
    for _ in range(count):
        iid, _, cnt = random.choice(active_pool)
        if iid == "money":
            pl.sc = pl.sc + cnt
        else:
            touched += st.add_item(inv, iid, cnt, pl=pl)
        result.append({"prop_id": iid, "count": cnt})

    pl.save_inventory(inv)
    gs = pl.update_gs()
    pl.save()
    log("gacha %s x%d -> %s" % (gacha_id, count, json.dumps(result)))
    return True, {
        "sc_current": pl.sc,
        "hc_current": pl.hc,
        "gs": gs,
        "token": pl.tokens(),
        "items": touched,
        "result": result,
        "is_gold_hit": 0,
        "gacha_info": {"discount": [], "mage": {}, "warrior": {}, "monk": {}},
    }


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


@handler("fusion")
def fusion(store, pid, msg):
    op = msg.get("op_type", "do_fusion")
    pl = st.Player(store, pid)
    inv = pl.inventory()
    pos = int(msg.get("FusionItemPos", -1))
    mats = [int(p) for p in (msg.get("MaterialItemPosList") or [])]

    mat_items = [st.item_at(inv, p) for p in mats]
    xp_sum = sum(st.item_fusion_xp_output(m) for m in mat_items if m is not None)
    if mats:
        st.take_positions(inv, mats)

    it = st.item_at(inv, pos)
    touched = []
    if it is not None:
        if op == "do_tutorial" and xp_sum <= 0:
            # In the fusion tutorial, grant enough XP to reach fusionLevel + 1
            fd = st.get_fusion_data(it)
            xp_sum = max(100, int(fd[2]))
            st.apply_fusion(it, xp_sum)
        else:
            need_sc = st.apply_fusion(it, xp_sum)
            if need_sc > 0:
                pl.sc = max(0, pl.sc - need_sc)
        touched.append(it)

    pl.save_inventory(inv)
    gs = pl.update_gs()
    pl.save()
    # UIFusion.OnFusionResponse loops over response["items"] and loads each entry into
    # _fusionItemInventory; only the upgraded target item must be in "items".
    return True, dict(st.currencies(pl), xp_sum=xp_sum, gs=gs, items=touched)


@handler("evolution")
def evolution(store, pid, msg):
    pl = st.Player(store, pid)
    inv = pl.inventory()
    pos = int(msg.get("evolution_item_pos", msg.get("EvolutionItemPos", msg.get("inventoryPos", -1))))
    it = st.item_at(inv, pos)
    touched = []
    if it is not None:
        info = st.ITEMS.get(str(it.get("_itemDataId", ""))) or {}
        lv = int(info.get("lv", 1))
        rare = int(info.get("r", 0))
        evol_lv = int(it.get("_evolutionLevel", 0) or 0)
        erow = st.EVOLUTION_LIST.get(f"{lv}_{rare}_{evol_lv}")
        if erow:
            cost_sc = int(erow[2] or 0)
            if cost_sc > 0:
                pl.sc = max(0, pl.sc - cost_sc)
            for mat_id, mat_cnt in erow[4] or []:
                st.take_item(inv, mat_id, int(mat_cnt))
        it["_evolutionLevel"] = evol_lv + 1
        it["_fusionLevel"] = 0
        it["_fusionXp"] = 0
        touched.append(it)
    pl.save_inventory(inv)
    gs = pl.update_gs()
    pl.save()
    return True, dict(st.currencies(pl), gs=gs, items=touched)


@handler("rune_socket")
def rune_socket(store, pid, msg):
    op = msg.get("op_type")
    pl = st.Player(store, pid)
    inv = pl.inventory()
    if op == "socket":
        rune_id = str(msg.get("itemId", ""))
        gone = st.take_item(inv, rune_id, 1) if rune_id else []
        pl.save_inventory(inv)
        gs = pl.update_gs()
        pl.save()
        return True, dict(st.currencies(pl), is_success=1, gs=gs, items=gone)
    if op in ("drill", "rune_remove", "rune_upgrade"):
        pl.save_inventory(inv)
        gs = pl.update_gs()
        pl.save()
        return True, dict(st.currencies(pl), is_success=1, gs=gs, items=[])
    log("rune_socket/%s not implemented: %s" % (op, json.dumps(msg)[:200]))
    return st.error(NOT_AVAILABLE)
