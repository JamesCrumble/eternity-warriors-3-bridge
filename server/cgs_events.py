"""CGS: login bonuses, live events, purchases, social features, quests.

What Glu ran as live operations is answered as "nothing running": the client
then hides the panels instead of waiting. Real-money purchases, friends and
invite codes need services that no longer exist and fail with a message box.
Every answer here has the shape its client parser reads (named per handler).
"""
import json
import time

from cgs import handler, log
import cgs_state as st

NOT_AVAILABLE = "99999"


def now():
    return int(time.time())


@handler("get_room_name")
def get_room_name(store, pid, msg):
    # ChatManager.OnGetRoomNameResponse: the town's chat/presence room.
    return True, {"roomName": "town_%s_1" % (msg.get("language") or "en")}


@handler("get_cgs_name")
def get_cgs_name(store, pid, msg):
    # LiveOpsManager.DoCheckLiveOpsVersion reads remain_maintain_time and closed_service without
    # a null check: missing, the coroutine dies with IsUpdatingLiveOpsData stuck true and entering
    # a story level waits on it forever ("Accessing Network"). No "cgs_id" keeps the client's own.
    # The LiveOps files it then fetches 404, which ends the check through OnUpdateFailed.
    return True, {"test_group": "C", "remain_maintain_time": -1, "version": "0",
                  "closed_service": ["guild", "leaderboard", "chat"]}


@handler("tournament")
def tournament(store, pid, msg):
    if msg.get("op_type") == "get_tournament_list":
        return True, []                 # TournamentManager casts the payload to ArrayList
    log("tournament/%s not implemented" % msg.get("op_type"))
    return True, {}


# ---- login bonuses --------------------------------------------------------------------

@handler("daily_bonus")
def daily_bonus(store, pid, msg):
    op = msg.get("op_type")
    if op == "request_bonus_state":
        # DailyBonusManager.OnGetServerBonusState: bonus_state 0 = nothing to claim today.
        return True, {"active_days": 1, "bonus_state": 0, "time": now()}
    if op == "claim_bonus":
        pl = st.Player(store, pid)
        return True, dict(st.currencies(pl), active_days=1)
    log("daily_bonus/%s not implemented" % op)
    return True, {}


@handler("starter")
def starter(store, pid, msg):
    op = msg.get("op_type")
    if op == "received_info":
        # current_day >= 8: the 7-day starter bonus is over, the client does not open it.
        return True, {"current_day": 8, "state": 0, "time": now(), "received_history": []}
    log("starter/%s: the starter bonus is over" % op)
    return st.error(NOT_AVAILABLE)


@handler("campaign")
def campaign(store, pid, msg):
    # TieredSpenderHcManager.ParseTieredSpenderState: an empty campaign_id = none running.
    return True, {"campaign_id": ""}


@handler("month_card")
def month_card(store, pid, msg):
    op = msg.get("op_type")
    if op == "state":
        # UIMonthCard.OnMonthCard: no card bought, the offer is closed.
        return True, {"state": 0, "remain_days": 0, "is_open": 0}
    log("month_card/%s: real-money purchases are not available" % op)
    return st.error(NOT_AVAILABLE)


@handler("energy")
def energy(store, pid, msg):
    op = msg.get("op_type")
    if op == "get_energy_value":
        kind = msg.get("type") or "tower"
        return True, {kind: {"next_point": 0, "energy_value": 10, "max_point": 10, "one_price": 10},
                      "energy_value": 10, "max_point": 10, "price": 10}
    if op == "get_info":
        return True, {}             # per-type energy: none, levels cost nothing
    log("energy/%s: energy is not sold (levels cost none)" % op)
    return st.error(NOT_AVAILABLE)


# ---- purchases and offers --------------------------------------------------------------

@handler("iap")
def iap(store, pid, msg):
    op = msg.get("op_type")
    if op in ("get_iap_reward_status", "get_iap_reward"):
        return True, {}             # FirstPayEventManager: an empty table = no first-purchase event
    log("iap/%s: real-money purchases are not available" % op)
    return st.error(NOT_AVAILABLE)


@handler("tapjoy")
def tapjoy(store, pid, msg):
    log("tapjoy/%s: ad networks are gone" % msg.get("op_type"))
    return st.error(NOT_AVAILABLE)


@handler("soulstore")
def soulstore(store, pid, msg):
    op = msg.get("op_type")
    pl = st.Player(store, pid)
    if op in ("get", "refresh"):
        # SoulStoreManager.OnDownloadSoulStoreAttributes: no stock (filled from data later).
        return True, {"item_info": [], "refresh_hc": 0, "hc_current": pl.hc}
    log("soulstore/%s: the soul store has no stock" % op)
    return st.error(NOT_AVAILABLE)


# ---- social -------------------------------------------------------------------------------

@handler("invite")
def invite(store, pid, msg):
    if msg.get("op_type") == "invite_code_info":
        return True, {"switch": 0}  # FriendManager: invite codes switched off
    return st.error(NOT_AVAILABLE)


@handler("friend")
def friend(store, pid, msg):
    log("friend/%s: no other players on this server" % msg.get("op_type"))
    return st.error(NOT_AVAILABLE)


@handler("gift")
def gift(store, pid, msg):
    return True, {}


# ---- quests ---------------------------------------------------------------------------------
# The quest table is the game's own (tools/dump_quests.py -> generated/quests.json). Active =
# not yet claimed and its prequest claimed; the client tracks the progress itself.

import os
_QUESTS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated", "quests.json")))
_QUEST_BY_ID = {q["quest_id"]: q for q in _QUESTS}


def _player_level(pl):
    try:
        basic = json.loads(pl.get(pl.role + "_basic") or "{}")
        lvl = int(basic.get("_currentLevel") or 0)
        if lvl > 0:
            return lvl
    except (ValueError, TypeError):
        pass
    return max(1, pl.get_int("level", 1))


# Daily combat quest unlock prerequisite -> expiration quest (stored in QuestDB's prequest_id field)
_DAILY_COMBAT_UNLOCK = {
    4001: 2003, 4002: 2004, 4003: 2005,
    4004: 2010, 4005: 2010, 4006: 2010,
    4007: 2014, 4008: 2014, 4009: 2014,
    4010: 2019, 4011: 2019, 4012: 2019,
    4013: 2023, 4014: 2023, 4015: 2023,
    4031: 2105, 4032: 2105, 4033: 2105,
    4034: 2110, 4035: 2110, 4036: 2110,
    4037: 2114, 4038: 2114, 4039: 2114,
    4040: 2119, 4041: 2119, 4042: 2119,
    4043: 2123, 4044: 2123, 4045: 2123,
    4016: 2024, 4017: 2030, 4046: 2125, 4047: 2130,
}


def _claimed(pl):
    try:
        done = set(json.loads(pl.get(pl.role + "_quests_claimed") or "[]"))
    except ValueError:
        done = set()
    today = time.strftime("%Y-%m-%d", time.gmtime())
    last_day = pl.get(pl.role + "_daily_date")
    if last_day != today:
        if last_day:
            done = {qid for qid in done if not (4000 <= qid < 4200 or 5100 <= qid < 5200)}
            pl.set(pl.role + "_quests_claimed", json.dumps(sorted(done)))
        pl.set(pl.role + "_daily_date", today)
        pl.save()
    return done


def _active(pl):
    done = _claimed(pl)
    pl_lvl = _player_level(pl)
    enabled = [q for q in _QUESTS if q.get("status", 1) == 1 and q["quest_id"] not in done]

    active_ids = []

    # 1. Tutorial quests (1000..1999)
    for q in enabled:
        qid = q["quest_id"]
        if 1000 <= qid < 2000 and (q["prequest_id"] < 0 or q["prequest_id"] in done):
            active_ids.append(qid)

    # 2. Normal Story chain (2000..2099): only the next unclaimed quest in order
    normal_story = sorted((q["quest_id"] for q in enabled if 2000 <= q["quest_id"] < 2100))
    if normal_story:
        active_ids.append(normal_story[0])

    # 3. Hard Story chain (2100..2199): unlocked after Greece Boss (2006), one at a time
    if 2006 in done:
        hard_story = sorted((q["quest_id"] for q in enabled if 2100 <= q["quest_id"] < 2200))
        if hard_story:
            active_ids.append(hard_story[0])

    # 4. Normal Side Quests (3000..3099): up to 2 active at a time in order
    normal_side = sorted((q["quest_id"] for q in enabled if 3000 <= q["quest_id"] < 3100))
    active_ids.extend(normal_side[:2])

    # 5. Hard Side Quests (3100..3199): unlocked after 2101, up to 2 active at a time
    if 2101 in done:
        hard_side = sorted((q["quest_id"] for q in enabled if 3100 <= q["quest_id"] < 3200))
        active_ids.extend(hard_side[:2])

    # 6. Daily Combat Quests (4000..4099): unlocked by story progress, retired when q["prequest_id"] is done
    dailies = []
    for q in enabled:
        qid = q["quest_id"]
        if 4000 <= qid < 4100:
            unlock_q = _DAILY_COMBAT_UNLOCK.get(qid)
            expire_q = q["prequest_id"]
            if unlock_q and unlock_q in done and (expire_q < 0 or expire_q not in done):
                dailies.append(qid)
    active_ids.extend(sorted(dailies))

    # 7. Daily Fusion quest (4100..4199): all 4101..4117 are level-bracketed variants of IDS_STR_QUEST_4001.
    # Offer at most one per day (only if no 4100..4199 quest has been claimed today).
    if not any(4100 <= d < 4200 for d in done):
        lvl_quests = sorted(
            q["quest_id"]
            for q in enabled
            if 4100 <= q["quest_id"] < 4200
            and q["visible_player_level_low"] <= pl_lvl <= q["visible_player_level_high"]
        )
        if lvl_quests:
            active_ids.append(lvl_quests[0])

    # 8. Endless Tower Quests (5000..5999): unlocked after 2006
    if 2006 in done:
        tower_story = sorted((q["quest_id"] for q in enabled if 5000 <= q["quest_id"] < 5100 or 5500 <= q["quest_id"] < 5600))
        if tower_story:
            active_ids.append(tower_story[0])
        if 5100 not in done:
            active_ids.append(5100)
        if 2024 in done and 5101 not in done:
            active_ids.append(5101)

    return [str(qid) for qid in active_ids]


@handler("quest")
def quest(store, pid, msg):
    op = msg.get("op_type")
    pl = st.Player(store, pid)
    if op == "get_quest_list":
        return True, _active(pl)    # QuestManager.ParseActiveQuestIdList: ids as strings
    if op == "claim_reward":
        qid = int(msg.get("quest_id", -1))
        q = _QUEST_BY_ID.get(qid)
        done = _claimed(pl)
        if q is None or qid in done:
            return st.error(NOT_AVAILABLE)
        done.add(qid)
        pl.set(pl.role + "_quests_claimed", json.dumps(sorted(done)))
        pl.xp = pl.xp + q["reward_exp"]
        pl.sc = pl.sc + q["reward_sc"]
        pl.hc = pl.hc + q["reward_hc"]
        inv = pl.inventory()
        touched = []
        role_index = st.ROLES.index(pl.role)
        for it in q["reward_item_list"]:
            if it["reward_role"] in (-1, role_index):
                touched += st.add_item(inv, it["reward_item_id"], it["reward_item_count"], pl=pl)
        pl.save_inventory(inv)
        gs = pl.update_gs()
        pl.save()
        log("quest %d claimed: +%d xp +%d sc +%d hc, %d item(s), tokens=%s" % (
            qid, q["reward_exp"], q["reward_sc"], q["reward_hc"], len(touched), json.dumps(pl.tokens())))
        return True, dict(st.currencies(pl), exp=pl.xp, gs=gs, token=pl.tokens(), items=touched,
                          quest_id_list=_active(pl))
    log("quest/%s not implemented: %s" % (op, json.dumps(msg)[:200]))
    return st.error(NOT_AVAILABLE)
