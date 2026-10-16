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


def _claimed(pl):
    try:
        return set(json.loads(pl.get(pl.role + "_quests_claimed") or "[]"))
    except ValueError:
        return set()


def _active(pl):
    done = _claimed(pl)
    return [str(q["quest_id"]) for q in _QUESTS
            if q["quest_id"] not in done and (q["prequest_id"] < 0 or q["prequest_id"] in done)]


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
                touched += st.add_item(inv, it["reward_item_id"], it["reward_item_count"])
        pl.save_inventory(inv)
        pl.save()
        log("quest %d claimed: +%d xp +%d sc +%d hc, %d item(s)" % (qid, q["reward_exp"], q["reward_sc"],
                                                                   q["reward_hc"], len(touched)))
        return True, dict(st.currencies(pl), exp=pl.xp, items=touched, quest_id_list=_active(pl))
    log("quest/%s not implemented: %s" % (op, json.dumps(msg)[:200]))
    return st.error(NOT_AVAILABLE)
