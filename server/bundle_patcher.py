#!/usr/bin/env python3
"""Patches Unity AssetBundles from the base OBB so all levels and enemies work without retired CDN extra_* bundles:

1. base_uniform_data-levels:
   - Clears extra_* bundles in BundlesConfig so the client never hangs trying to download missing bundles.
   - Remaps non-OBB _sceneName entries in LevelConfigNormal, LevelConfigHard, LevelConfigLegendary, LevelConfigSM,
     and LevelConfigPvP to existing OBB scenes ('greece_temple' for >=6 triggers, 'greece_market' for 5 triggers,
     'greece_market_night' for <=4 triggers), adjusting trigger counts and _chestInfos transforms/prefabs while
     preserving each level's logical _level ID, enemy waves, quest progression, and chest loot IDs.
   - Normalizes EnemyGroup _enemyType values so every enemy group matches an EnemySpot in its trigger (4 for
     final-trigger-only boss/elite groups, 0 for all other groups).

2. base_lvl_greece_1_scene:
   - Normalizes non-boss EnemySpot._enemyType (1, 2, 3 -> 0) in BuildPlayer-greece_market,
     BuildPlayer-greece_market_night, and BuildPlayer-greece_temple so every trigger (trigger_0..trigger_{K-1})
     has _enemyType=0 spots and the final trigger retains its _enemyType=4 Boss Spot (with HP bar & death camera).

3. base_uniform_global_manager:
   - Remaps non-OBB enemy character models in CharacterTable to existing OBB (agentPrefab, modelPrefab) pairs in-place
     so every AcData enemy ID (cyclop_B_Lv10, slime_*, catwoman_*, werebear_*, etc.) spawns and animates cleanly
     while preserving its exact AcData ID, stats, loot table, and kill-quest tracking.
"""
import lzma
import os
import struct
import zipfile
import zlib
from typing import Dict, List, Optional, Tuple


def _pack_str(s: str) -> bytes:
    b = s.encode("utf-8")
    out = struct.pack("<I", len(b)) + b
    while len(out) % 4 != 0:
        out += b"\x00"
    return out


def _decompress_unity3d(raw_bundle: bytes) -> Tuple[int, bytes, dict, bytearray]:
    pos = struct.unpack(">I", raw_bundle[31:35])[0]
    props = raw_bundle[pos : pos + 5]
    uncomp_size = struct.unpack("<Q", raw_bundle[pos + 5 : pos + 13])[0]
    filt = lzma._decode_filter_properties(lzma.FILTER_LZMA1, props)
    decomp = bytearray(
        lzma.LZMADecompressor(lzma.FORMAT_RAW, None, [filt]).decompress(
            raw_bundle[pos + 13 :], max_length=uncomp_size
        )
    )
    return pos, props, filt, decomp


def _compress_unity3d(raw_bundle: bytes, pos: int, props: bytes, filt: dict, decomp: bytes) -> bytes:
    comp = lzma.LZMACompressor(lzma.FORMAT_RAW, filters=[filt])
    lzma_raw = comp.compress(decomp) + comp.flush()
    lzma_with_hdr = props + struct.pack("<Q", len(decomp)) + lzma_raw

    new_bundle = bytearray(raw_bundle[:pos]) + lzma_with_hdr
    total_size = len(new_bundle)
    comp_size = len(lzma_with_hdr)
    new_bundle[27:31] = struct.pack(">I", total_size)
    new_bundle[43:47] = struct.pack(">I", comp_size)
    new_bundle[47:51] = struct.pack(">I", len(decomp))
    new_bundle[51:55] = struct.pack(">I", total_size)
    return bytes(new_bundle)


def _parse_level_config(body: bytes) -> List[dict]:
    pos = 0

    def r_i32():
        nonlocal pos
        v = struct.unpack_from("<i", body, pos)[0]
        pos += 4
        return v

    def r_str():
        nonlocal pos
        n = r_i32()
        s = body[pos : pos + n].decode("utf-8")
        pos = (pos + n + 3) & ~3
        return s

    def r_arr(fn):
        return [fn() for _ in range(r_i32())]

    levels = []
    for _ in range(r_i32()):
        levels.append(
            {
                "_level": r_str(),
                "_sceneName": r_str(),
                "_levelNameIDS": r_str(),
                "_levelDescIDS": r_str(),
                "_available": r_i32(),
                "_levelTips": r_arr(r_str),
                "_levelLoadingBGTexture": r_str(),
                "_unlockLevel": r_i32(),
                "_suggestLevel": r_i32(),
                "_preLevel": r_str(),
                "_cameraMode": r_i32(),
                "_timeOfMinScore": r_i32(),
                "_timeOfMaxScore": r_i32(),
                "_triggerID": r_i32(),
                "_enemies": r_arr(
                    lambda: {
                        "TriggerName": r_str(),
                        "Configs": r_arr(
                            lambda: {
                                "GroupConfigs": r_arr(
                                    lambda: {
                                        "GroupName": r_str(),
                                        "DelayTime": r_i32(),
                                    }
                                ),
                                "Possibility": r_i32(),
                            }
                        ),
                    }
                ),
                "_worldName": r_str(),
                "_nextWorldName": r_str(),
                "_missionId": r_i32(),
                "_chestInfos": r_arr(
                    lambda: {
                        "_id": r_str(),
                        "_transformName": r_str(),
                        "_count": r_i32(),
                        "_prefabPath": r_str(),
                    }
                ),
                "_largeChest": r_str(),
                "_largeChestPrefab": r_str(),
            }
        )
    assert pos == len(body), f"LevelConfig parse mismatch: {pos} != {len(body)}"
    return levels


def _serialize_level_config(levels: List[dict]) -> bytes:
    buf = bytearray()

    def w_i32(v: int):
        buf.extend(struct.pack("<i", v))

    def w_str(s: str):
        buf.extend(_pack_str(s))

    def w_arr(lst, fn):
        w_i32(len(lst))
        for item in lst:
            fn(item)

    w_i32(len(levels))
    for lv in levels:
        w_str(lv["_level"])
        w_str(lv["_sceneName"])
        w_str(lv["_levelNameIDS"])
        w_str(lv["_levelDescIDS"])
        w_i32(lv["_available"])
        w_arr(lv["_levelTips"], w_str)
        w_str(lv["_levelLoadingBGTexture"])
        w_i32(lv["_unlockLevel"])
        w_i32(lv["_suggestLevel"])
        w_str(lv["_preLevel"])
        w_i32(lv["_cameraMode"])
        w_i32(lv["_timeOfMinScore"])
        w_i32(lv["_timeOfMaxScore"])
        w_i32(lv["_triggerID"])
        w_arr(
            lv["_enemies"],
            lambda t: (
                w_str(t["TriggerName"]),
                w_arr(
                    t["Configs"],
                    lambda c: (
                        w_arr(
                            c["GroupConfigs"],
                            lambda g: (w_str(g["GroupName"]), w_i32(g["DelayTime"])),
                        ),
                        w_i32(c["Possibility"]),
                    ),
                ),
            ),
        )
        w_str(lv["_worldName"])
        w_str(lv["_nextWorldName"])
        w_i32(lv["_missionId"])
        w_arr(
            lv["_chestInfos"],
            lambda ch: (
                w_str(ch["_id"]),
                w_str(ch["_transformName"]),
                w_i32(ch["_count"]),
                w_str(ch["_prefabPath"]),
            ),
        )
        w_str(lv["_largeChest"])
        w_str(lv["_largeChestPrefab"])
    return bytes(buf)


IPA_SCENES = {
    "greece_cave", "greece_dungeon", "greece_boss",
    "China_bamboo", "China_bamboo_night", "China_bridge", "China_bridge_night",
    "China_town", "China_town_night", "China_ruin", "China_temple", "China_boss",
    "Gothic_grave", "Gothic_grave_night", "Gothic_swamp", "Gothic_swamp_night",
    "Gothic_town", "Gothic_town_night", "Gothic_church", "Gothic_dungeon", "Gothic_boss",
}


def patch_data_levels(raw_bundle: bytes, has_ipa: bool = True) -> bytes:
    pos, props, filt, decomp = _decompress_unity3d(raw_bundle)
    cab_off = 44
    cab = bytearray(decomp[cab_off:])
    meta_sz, file_sz, ver, data_off = struct.unpack_from(">IIII", cab, 0)
    nobjs = struct.unpack_from("<i", cab, 42)[0]

    objs = []
    by_name: Dict[str, int] = {}
    p = 46
    for idx in range(nobjs):
        pid, off, sz, tid, cid, unk = struct.unpack_from("<iiiihh", cab, p)
        p += 20
        o = data_off + off
        raw_obj = bytes(cab[o : o + sz])
        name = ""
        hdr_end = 0
        if cid == 114:
            nlen = struct.unpack_from("<I", raw_obj, 20)[0]
            name = raw_obj[24 : 24 + nlen].decode("utf-8", "replace")
            hdr_end = (24 + nlen + 3) & ~3
            by_name[name] = idx
        objs.append([pid, off, sz, tid, cid, unk, name, raw_obj[:hdr_end], raw_obj[hdr_end:]])

    # 1. Patch BundlesConfig
    b_idx = by_name["BundlesConfig"]
    worlds = [
        ("Background", "IDS_BUNDLE_TIPS_ARMORS"),
        ("Greece", "IDS_BUNDLE_TIPS_GREECE"),
        ("China", "IDS_BUNDLE_TIPS_CHINA"),
        ("Activity", "IDS_BUNDLE_TIPS_ACTIVITY"),
        ("Survival", "IDS_BUNDLE_TIPS_SM"),
        ("Gothic", "IDS_BUNDLE_TIPS_GOTHIC"),
        ("Ice", "IDS_BUNDLE_TIPS_ICE"),
        ("Crystal", "IDS_BUNDLE_TIPS_CRYSTAL"),
        ("Lava", "IDS_BUNDLE_TIPS_LAVA"),
    ]
    bc_buf = bytearray(struct.pack("<I", len(worlds)))
    for wname, wtips in worlds:
        bc_buf += _pack_str(wname)
        bc_buf += struct.pack("<I", 0)  # 0 bundles in _bundles
        bc_buf += _pack_str(wtips)
        bc_buf += struct.pack("<I", 0)  # _downloadInLaunch = false
    objs[b_idx][8] = bytes(bc_buf)

    # 2. Extract scene templates from LevelConfigNormal
    obb_scenes = {"town", "village", "village2", "greece_market", "greece_temple", "greece_market_night"}
    avail_scenes = (obb_scenes | IPA_SCENES) if has_ipa else obb_scenes
    normal_levels = _parse_level_config(objs[by_name["LevelConfigNormal"]][8])
    scene_templates = {}
    for lv in normal_levels:
        sc = lv["_sceneName"]
        if sc in avail_scenes and not lv["_level"].startswith("activity_"):
            scene_templates[sc] = (
                lv["_levelLoadingBGTexture"],
                [(c["_transformName"], c["_count"], c["_prefabPath"]) for c in lv["_chestInfos"]],
            )

    warmup_group_by_cfg = {
        "LevelConfigNormal": "Assets/Data/Level/EnemyGroup/skeleton_VE_Lv8.asset",
        "LevelConfigHard": "Assets/Data/Level/EnemyGroup/skeleton_VE_Lv28.asset",
        "LevelConfigLegendary": "Assets/Data/Level/EnemyGroup/skeleton_VE_Lv42.asset",
        "LevelConfigSM": "Assets/Data/Level/EnemyGroup/skeleton_VE_Lv8.asset",
        "LevelConfigPvP": "Assets/Data/Level/EnemyGroup/skeleton_VE_Lv8.asset",
    }

    non_final_groups = set()
    final_groups = set()

    for cname in ("LevelConfigNormal", "LevelConfigHard", "LevelConfigLegendary", "LevelConfigSM", "LevelConfigPvP"):
        c_idx = by_name[cname]
        levels = _parse_level_config(objs[c_idx][8])
        warmup_grp = warmup_group_by_cfg[cname]

        for lv in levels:
            sc = lv["_sceneName"]
            trigs = lv["_enemies"]

            if sc in avail_scenes:
                # Fix missing expansion loading BG on available scenes (e.g. activity_2015_cny_2 on Gothic_boss)
                if "Lava1" in lv["_levelLoadingBGTexture"] and sc in scene_templates:
                    lv["_levelLoadingBGTexture"] = scene_templates[sc][0]
            else:
                if cname in ("LevelConfigSM", "LevelConfigPvP"):
                    target_sc = "greece_market_night"
                    lv["_sceneName"] = target_sc
                    lv["_levelLoadingBGTexture"] = scene_templates[target_sc][0]
                elif has_ipa and sc in ("Ice_boss", "Crystal_boss", "boss", "China_boss_cny") and len(trigs) == 1:
                    target_sc = "China_boss" if sc == "China_boss_cny" else ("greece_boss" if sc == "Ice_boss" else "Gothic_boss")
                    lv["_sceneName"] = target_sc
                    lv["_levelLoadingBGTexture"] = scene_templates[target_sc][0]
                    trigs[0]["TriggerName"] = "trigger_0"
                elif len(trigs) >= 6:
                    target_sc = "greece_temple"
                    lv["_sceneName"] = target_sc
                    lv["_levelLoadingBGTexture"] = scene_templates[target_sc][0]
                    merged_gcs = []
                    for t in trigs[5:]:
                        for cfg in t["Configs"]:
                            merged_gcs.extend(cfg["GroupConfigs"])
                    new_trigs = []
                    for k in range(5):
                        new_trigs.append({"TriggerName": f"trigger_{k}", "Configs": trigs[k]["Configs"]})
                    new_trigs.append(
                        {
                            "TriggerName": "trigger_5",
                            "Configs": [{"GroupConfigs": merged_gcs, "Possibility": 1}],
                        }
                    )
                    lv["_enemies"] = new_trigs
                elif len(trigs) == 5:
                    target_sc = "greece_market"
                    lv["_sceneName"] = target_sc
                    lv["_levelLoadingBGTexture"] = scene_templates[target_sc][0]
                    for k in range(5):
                        trigs[k]["TriggerName"] = f"trigger_{k}"
                else:
                    target_sc = "greece_market_night"
                    lv["_sceneName"] = target_sc
                    lv["_levelLoadingBGTexture"] = scene_templates[target_sc][0]
                    if len(trigs) == 4:
                        for k in range(4):
                            trigs[k]["TriggerName"] = f"trigger_{k}"
                    elif len(trigs) > 0:
                        boss_gcs = []
                        for t in trigs:
                            for cfg in t["Configs"]:
                                boss_gcs.extend(cfg["GroupConfigs"])
                        lv["_enemies"] = [
                            {
                                "TriggerName": f"trigger_{k}",
                                "Configs": [
                                    {
                                        "GroupConfigs": [{"GroupName": warmup_grp, "DelayTime": 0}],
                                        "Possibility": 1,
                                    }
                                ],
                            }
                            for k in range(3)
                        ] + [
                            {
                                "TriggerName": "trigger_3",
                                "Configs": [{"GroupConfigs": boss_gcs, "Possibility": 1}],
                            }
                        ]

                if lv["_chestInfos"] and lv["_sceneName"] in scene_templates:
                    cid = lv["_chestInfos"][0]["_id"]
                    lv["_chestInfos"] = [
                        {"_id": cid, "_transformName": tn, "_count": cnt, "_prefabPath": pp}
                        for tn, cnt, pp in scene_templates[lv["_sceneName"]][1]
                    ]

            # Record which groups appear on non-final vs final triggers
            cur_trigs = lv["_enemies"]
            if cname in ("LevelConfigNormal", "LevelConfigHard", "LevelConfigLegendary") and cur_trigs:
                for k, t in enumerate(cur_trigs):
                    is_last = k == len(cur_trigs) - 1
                    for cfg in t["Configs"]:
                        for gc in cfg["GroupConfigs"]:
                            gname = gc["GroupName"].split("/")[-1].replace(".asset", "").lower()
                            if is_last:
                                final_groups.add(gname)
                            else:
                                non_final_groups.add(gname)

        objs[c_idx][8] = _serialize_level_config(levels)

    # 3. Normalize EnemyGroup._enemyInfos[]._enemyType in-place
    # Every trigger in our scenes has _enemyType=0 spots, and the final trigger also has an _enemyType=4 Boss Spot.
    for obj in objs:
        pid, off, sz, tid, cid, unk, name, hdr, body = obj
        if cid == 114 and tid == -1:
            gname_low = name.lower()
            only_final = (gname_low in final_groups) and (gname_low not in non_final_groups)
            b_arr = bytearray(body)
            cnt = struct.unpack_from("<i", b_arr, 0)[0]
            pos_e = 4
            for _ in range(cnt):
                n1 = struct.unpack_from("<i", b_arr, pos_e)[0]
                pos_e = (pos_e + 4 + n1 + 3) & ~3
                n2 = struct.unpack_from("<i", b_arr, pos_e)[0]
                pos_e = (pos_e + 4 + n2 + 3) & ~3
                grd, etype, widx = struct.unpack_from("<iii", b_arr, pos_e)
                new_etype = 4 if (only_final and etype in (4, 5, 6)) else 0
                struct.pack_into("<i", b_arr, pos_e + 4, new_etype)
                pos_e += 12
            obj[8] = bytes(b_arr)

    # 4. Rebuild CAB-base_uniform_data-levels data section with 8-byte alignment
    order = sorted(range(nobjs), key=lambda i: objs[i][1])
    data_buf = bytearray()
    for i in order:
        while len(data_buf) % 8 != 0:
            data_buf.append(0)
        new_off = len(data_buf)
        full_obj = objs[i][7] + objs[i][8]
        data_buf.extend(full_obj)
        objs[i][1] = new_off
        objs[i][2] = len(full_obj)

    new_cab = bytearray(cab[:data_off]) + data_buf
    new_file_sz = len(new_cab)
    struct.pack_into(">I", new_cab, 4, new_file_sz)
    p = 46
    for i in range(nobjs):
        pid, off, sz, tid, cid, unk = objs[i][:6]
        struct.pack_into("<iiiihh", new_cab, p, pid, off, sz, tid, cid, unk)
        p += 20

    new_decomp = bytearray(decomp[:cab_off]) + new_cab
    struct.pack_into(">I", new_decomp, 37, new_file_sz)
    return _compress_unity3d(raw_bundle, pos, props, filt, bytes(new_decomp))


def patch_greece_1_scene(raw_bundle: bytes) -> bytes:
    """Set all non-boss EnemySpot._enemyType (1, 2, 3) to 0 in-place in greece_market,
    greece_market_night, and greece_temple."""
    pos, props, filt, decomp = _decompress_unity3d(raw_bundle)
    num_files = struct.unpack_from(">I", decomp, 0)[0]
    p = 4
    patched_spots = 0
    for _ in range(num_files):
        end = decomp.index(b"\x00", p)
        fname = decomp[p:end].decode()
        p = end + 1
        foff, fsize = struct.unpack_from(">II", decomp, p)
        p += 8
        if fname.endswith(".sharedAssets"):
            continue
        cab_mv = memoryview(decomp)[foff : foff + fsize]
        _, _, _, data_off = struct.unpack_from(">IIII", cab_mv, 0)
        op = 42
        nobjs = struct.unpack_from("<i", cab_mv, op)[0]
        op += 4
        gos = {}
        transforms = {}
        monos = {}
        for _ in range(nobjs):
            pid, off, sz, tid, cid, unk = struct.unpack_from("<iiiihh", cab_mv, op)
            op += 20
            o = data_off + off
            if cid == 1:
                nc = struct.unpack_from("<i", cab_mv, o)[0]
                gpos = o + 4 + nc * 12 + 4
                nlen = struct.unpack_from("<i", cab_mv, gpos)[0]
                gos[pid] = bytes(cab_mv[gpos + 4 : gpos + 4 + nlen]).decode("utf-8", "replace")
            elif cid == 4:
                go_pid = struct.unpack_from("<i", cab_mv, o + 4)[0]
                nch = struct.unpack_from("<i", cab_mv, o + 48)[0]
                ch = [struct.unpack_from("<i", cab_mv, o + 52 + k * 8 + 4)[0] for k in range(nch)]
                transforms[pid] = (go_pid, ch)
            elif cid == 114 and sz == 40:
                go_pid = struct.unpack_from("<i", cab_mv, o + 4)[0]
                monos.setdefault(go_pid, []).append(foff + o)

        for tpid, (gpid, ch) in transforms.items():
            gname = gos.get(gpid, "")
            if gname.startswith("trigger_"):
                for cpid in ch:
                    if cpid in transforms:
                        cgpid = transforms[cpid][0]
                        for abs_o in monos.get(cgpid, []):
                            etype = struct.unpack_from("<i", decomp, abs_o + 24)[0]
                            if etype in (1, 2, 3):
                                struct.pack_into("<i", decomp, abs_o + 24, 0)
                                patched_spots += 1

    assert patched_spots > 0, "Expected to patch EnemySpot instances in base_lvl_greece_1_scene"
    return _compress_unity3d(raw_bundle, pos, props, filt, bytes(decomp))


def patch_global_manager(raw_bundle: bytes, has_ipa: bool = True) -> bytes:
    """Remap unavailable enemy characters in CharacterTable to available OBB/IPA (agentPrefab, modelPrefab) pairs,
    and update AcDataList._equipList for remapped characters so their monster weapons match the target skeleton."""
    pos, props, filt, decomp = _decompress_unity3d(raw_bundle)
    cab_off = struct.unpack_from(">I", decomp, 36)[0]
    cab = bytearray(decomp[cab_off:])
    meta_sz, file_sz, ver, data_off = struct.unpack_from(">IIII", cab, 0)
    nobjs = struct.unpack_from("<i", cab, 42)[0]

    objs = []
    by_name: Dict[str, int] = {}
    p = 46
    for idx in range(nobjs):
        pid, off, sz, tid, cid, unk = struct.unpack_from("<iiiihh", cab, p)
        p += 20
        o = data_off + off
        raw_obj = bytes(cab[o : o + sz])
        name = ""
        hdr_end = 0
        if cid == 114:
            nlen = struct.unpack_from("<I", raw_obj, 20)[0]
            name = raw_obj[24 : 24 + nlen].decode("utf-8", "replace")
            hdr_end = (24 + nlen + 3) & ~3
            by_name[name] = idx
        objs.append([pid, off, sz, tid, cid, unk, name, raw_obj[:hdr_end], raw_obj[hdr_end:]])

    ct_idx = by_name["CharacterTable"]
    ct_body = objs[ct_idx][8]
    r_pos = 0

    def r_ct_i32():
        nonlocal r_pos
        v = struct.unpack_from("<i", ct_body, r_pos)[0]
        r_pos += 4
        return v

    def r_ct_str():
        nonlocal r_pos
        n = r_ct_i32()
        s = ct_body[r_pos : r_pos + n].decode("utf-8")
        r_pos = (r_pos + n + 3) & ~3
        return s

    entries = [[r_ct_str(), r_ct_str(), r_ct_str()] for _ in range(r_ct_i32())]
    assert r_pos == len(ct_body)

    obb_ok = {
        "mage0", "mage0_pvp", "mage_town", "mage_town_friend", "mage_preview", "mage_selection", "mage_statue",
        "warrior0", "warrior0_pvp", "warrior_town", "warrior_town_friend", "warrior_preview", "warrior_selection", "warrior_statue",
        "monk0", "monk0_pvp", "monk_town", "monk_town_friend", "monk_preview", "monk_selection", "monk_statue",
        "skeleton_normal", "skeleton_tutorial", "skeleton_asian_normal", "skeleton_archer", "skeleton_archer_elite",
        "skeleton_hammer_elite", "skeleton_sword_boss", "specialBoss_3",
        "bat_normal", "bat_lighting_normal",
        "wolf_normal", "wolf_elite",
        "zombie_normal", "zombie_poison_elite", "zombie_lighting_elite", "zombie_boss",
    }
    ipa_ok = {
        "raven_normal",
        "ball_normal", "ball_elite", "ball_boss",
        "cyclop_elite", "cyclop_boss",
        "slime_normal", "slime_poison_elite",
        "wolfman_elite", "wolfman_boss",
        "boarman_elite", "boarman_boss", "daily_boarman_boss",
        "catwoman_elite", "catwoman_boss",
        "werebear_elite", "werebear_boss", "daily_werebear_boss",
        "kylin_elite", "kylin_boss", "kylin_ice_boss",
        "eragon_elite", "eragon_boss",
    }
    avail_chars = (obb_ok | ipa_ok) if has_ipa else obb_ok
    by_cid = {c: (a, m) for c, a, m in entries if c in avail_chars}

    def pick_target_char(c: str) -> str:
        cl = c.lower()
        if has_ipa:
            if "cyclop" in cl:
                return "cyclop_boss" if "boss" in cl else "cyclop_elite"
            if "boarman" in cl:
                return "boarman_boss" if "boss" in cl else "boarman_elite"
            if "werebear" in cl or "war_cny" in cl:
                return "werebear_boss" if "boss" in cl else "werebear_elite"
            if "eragon" in cl or "minotaur" in cl or "goat" in cl:
                return "eragon_boss" if "boss" in cl else "eragon_elite"
            if "wolfman" in cl or c == "specialBoss_1":
                return "wolfman_boss" if ("boss" in cl or c == "specialBoss_1") else "wolfman_elite"
            if "catwoman" in cl or "rabbit" in cl or c == "specialBoss_2":
                return "catwoman_boss" if ("boss" in cl or c == "specialBoss_2") else "catwoman_elite"
            if "kylin" in cl:
                return "kylin_boss" if "boss" in cl else "kylin_elite"
            if "slime" in cl:
                return "slime_poison_elite" if ("elite" in cl or "boss" in cl) else "slime_normal"
            if "ball" in cl or "egg" in cl:
                return "ball_boss" if "boss" in cl else ("ball_elite" if "elite" in cl else "ball_normal")
            if "raven" in cl:
                return "raven_normal"
        if any(k in cl for k in ("raven", "ball", "egg", "gargoyle", "bat")):
            return "bat_lighting_normal" if ("elite" in cl or "boss" in cl or "lighting" in cl) else "bat_normal"
        if "archer" in cl:
            return "skeleton_archer_elite" if ("elite" in cl or "boss" in cl) else "skeleton_archer"
        if "slime" in cl:
            return "zombie_poison_elite" if ("elite" in cl or "boss" in cl or "poison" in cl) else "zombie_normal"
        if any(k in cl for k in ("wolf", "spider", "catwoman", "rabbit", "kylin")):
            return "wolf_elite" if ("elite" in cl or "boss" in cl) else "wolf_normal"
        if any(k in cl for k in ("cyclop", "werebear", "boarman", "minotaur", "eragon", "goat", "war_cny", "specialboss")):
            return "specialBoss_3" if "boss" in cl else "skeleton_hammer_elite"
        if "hammer" in cl or "spear" in cl:
            return "skeleton_hammer_elite"
        if "sword" in cl:
            return "skeleton_sword_boss"
        if "zombie" in cl:
            return "zombie_boss" if "boss" in cl else ("zombie_lighting_elite" if "elite" in cl else "zombie_normal")
        return "skeleton_asian_normal"

    char_remap: Dict[str, str] = {}
    new_entries = []
    for c, a, m in entries:
        if c in avail_chars:
            new_entries.append([c, a, m])
        else:
            tc = pick_target_char(c)
            char_remap[c] = tc
            na, nm = by_cid[tc]
            new_entries.append([c, na, nm])

    ct_buf = bytearray(struct.pack("<I", len(new_entries)))
    for c, a, m in new_entries:
        ct_buf += _pack_str(c) + _pack_str(a) + _pack_str(m)
    objs[ct_idx][8] = bytes(ct_buf)

    # Update AcDataList._equipList for remapped characters so weapon prefabs & sockets match the target character
    ac_idx = by_name["AcDataList"]
    ac_body = objs[ac_idx][8]
    ap = 0

    def r_ac_i32():
        nonlocal ap
        v = struct.unpack_from("<i", ac_body, ap)[0]
        ap += 4
        return v

    def r_ac_str():
        nonlocal ap
        n = r_ac_i32()
        s = ac_body[ap : ap + n].decode("utf-8")
        ap = (ap + n + 3) & ~3
        return s

    ac_cnt = r_ac_i32()
    ac_entries = []
    canonical_equips: Dict[str, List[Tuple[str, int]]] = {}
    for _ in range(ac_cnt):
        acid = r_ac_str()
        cid_str = r_ac_str()
        cids = r_ac_str()
        nids = r_ac_str()
        stats_92 = ac_body[ap : ap + 92]
        ap += 92
        eq_cnt = r_ac_i32()
        eqs = [(r_ac_str(), r_ac_i32()) for _ in range(eq_cnt)]
        tail_88 = ac_body[ap : ap + 88]
        ap += 88
        if cid_str in avail_chars and eqs and cid_str not in canonical_equips:
            canonical_equips[cid_str] = eqs
        ac_entries.append([acid, cid_str, cids, nids, stats_92, eqs, tail_88])
    assert ap == len(ac_body), f"AcDataList parse mismatch: {ap} != {len(ac_body)}"

    ac_buf = bytearray(struct.pack("<I", len(ac_entries)))
    for acid, cid_str, cids, nids, stats_92, eqs, tail_88 in ac_entries:
        if cid_str in char_remap:
            tc = char_remap[cid_str]
            if tc in canonical_equips:
                eqs = canonical_equips[tc]
        ac_buf += _pack_str(acid) + _pack_str(cid_str) + _pack_str(cids) + _pack_str(nids)
        ac_buf += stats_92
        ac_buf += struct.pack("<I", len(eqs))
        for w_id, w_flag in eqs:
            ac_buf += _pack_str(w_id) + struct.pack("<i", w_flag)
        ac_buf += tail_88
    objs[ac_idx][8] = bytes(ac_buf)

    # Rebuild CAB-base_uniform_global_manager data section with 8-byte alignment
    order = sorted(range(nobjs), key=lambda i: objs[i][1])
    data_buf = bytearray()
    for i in order:
        while len(data_buf) % 8 != 0:
            data_buf.append(0)
        new_off = len(data_buf)
        full_obj = objs[i][7] + objs[i][8]
        data_buf.extend(full_obj)
        objs[i][1] = new_off
        objs[i][2] = len(full_obj)

    new_cab = bytearray(cab[:data_off]) + data_buf
    new_file_sz = len(new_cab)
    struct.pack_into(">I", new_cab, 4, new_file_sz)
    p = 46
    for i in range(nobjs):
        pid, off, sz, tid, cid, unk = objs[i][:6]
        struct.pack_into("<iiiihh", new_cab, p, pid, off, sz, tid, cid, unk)
        p += 20

    new_decomp = bytearray(decomp[:cab_off]) + new_cab
    struct.pack_into(">I", new_decomp, 40, new_file_sz)
    return _compress_unity3d(raw_bundle, pos, props, filt, bytes(new_decomp))


def extract_obb_shaders(raw_shaders_bundle: bytes) -> Dict[int, bytes]:
    """Extract 4.6.1p5 Android Shader (cid=48) objects by pathID from base_uniform_shaders."""
    _, _, _, decomp = _decompress_unity3d(raw_shaders_bundle)
    end = decomp.index(b"\x00", 4)
    cab_off, cab_sz = struct.unpack_from(">II", decomp, end + 1)
    cab = decomp[cab_off : cab_off + cab_sz]
    _, _, _, data_off = struct.unpack_from(">IIII", cab, 0)
    nobjs = struct.unpack_from("<i", cab, 42)[0]
    shaders: Dict[int, bytes] = {}
    p = 46
    for _ in range(nobjs):
        pid, off, sz, tid, cid, unk = struct.unpack_from("<iiiihh", cab, p)
        p += 20
        if cid == 48:
            shaders[pid] = bytes(cab[data_off + off : data_off + off + sz])
    return shaders


_ROOT_ANIM_IDS = {
    0x0934FEA1: 0,
    0x7E33CE37: 1,
    0xE73A9F8D: 2,
    0x0FFF3C4A: 3,
    0x78F80CDC: 4,
    0xE1F15D66: 5,
    0x9F4021DB: 6,
}

_WEP_MONSTER_SUBDIRS = [
    ("weapon_ball_head_0", "ball_head_0"),
    ("weapon_boarman_0", "boarman_0"),
    ("weapon_boarman_1", "boarman_1"),
    ("weapon_catwoman_0", "catwoman_0"),
    ("weapon_cyclop_0", "cyclop_0"),
    ("weapon_cyclop_1", "cyclop_1"),
    ("weapon_cyclop_foot_0", "cyclop_foot"),
    ("weapon_eragon_0", "eragon_0"),
    ("weapon_raven_head_0", "raven_head_0"),
    ("weapon_slime_0", "slime_0"),
    ("weapon_slime_1", "slime_1"),
    ("weapon_werebear_0", "werebear_0"),
    ("weapon_werebear_1", "werebear_1"),
    ("weapon_wolfman_", "wolfman"),
]

_CHAR_DIR_CASE_MAP = [
    ("assets/characters/ball/ball/", ["Assets/Characters/ball/ball/", "Assets/Characters/Ball/ball/"]),
    ("assets/characters/flyer/raven/", ["Assets/Characters/Flyer/raven/"]),
    ("assets/characters/fourfooted/kylin/", ["Assets/Characters/FourFooted/kylin/"]),
    ("assets/characters/giant/", ["Assets/Characters/Giant/"]),
    ("assets/characters/invertedlegs/", ["Assets/Characters/InvertedLegs/"]),
    ("assets/characters/soft/slime/", ["Assets/Characters/Soft/slime/"]),
]


def _avatar_lmap(d: bytes) -> Dict[int, int]:
    nl = struct.unpack_from("<I", d, 0)[0]
    pos = ((4 + nl + 3) & ~3) + 4
    n_cnt = struct.unpack_from("<I", d, pos)[0]
    pos += 4
    nodes = [struct.unpack_from("<ii", d, pos + i * 8) for i in range(n_cnt)]
    pos += n_cnt * 8
    id_cnt = struct.unpack_from("<I", d, pos)[0]
    pos += 4
    ids = list(struct.unpack_from(f"<{id_cnt}I", d, pos))
    pos += id_cnt * 4
    ax_cnt = struct.unpack_from("<I", d, pos)[0]
    pos += 4 + ax_cnt * 80
    xp_cnt = struct.unpack_from("<I", d, pos)[0]
    pos += 4 + xp_cnt * 48 + 536
    hsi_cnt = struct.unpack_from("<I", d, pos)[0]
    pos += 4 + hsi_cnt * 4 + 52
    tos_cnt = struct.unpack_from("<I", d, pos)[0]
    pos += 4
    tos = {}
    for _ in range(tos_cnt):
        k, sl = struct.unpack_from("<II", d, pos)
        pos += 8
        tos[k] = d[pos : pos + sl].decode("utf-8")
        pos = (pos + sl + 3) & ~3
    full_paths = [""] * n_cnt
    lmap: Dict[int, int] = {}
    for i in range(1, n_cnt):
        par = nodes[i][0]
        bname = tos[ids[i]]
        full_paths[i] = bname if par <= 0 else f"{full_paths[par]}/{bname}"
        lmap[ids[i]] = zlib.crc32(full_paths[i].encode("utf-8"))
    return lmap


def _convert_serialized_file(
    cab: bytes,
    bundle_name: str,
    is_scene: bool,
    obb_shaders: Optional[Dict[int, bytes]] = None,
) -> bytes:
    """Convert an inner CAB-* / BuildPlayer-* SerializedFile from Unity 4.2.1f4 (iOS) to 4.6.1p5 (Android)."""
    meta_sz, file_sz, ver, data_off = struct.unpack_from(">IIII", cab, 0)
    assert cab[20:30] == b"4.2.1f4\n1\x00", f"Unexpected u_ver: {cab[20:30]!r}"
    nobjs = struct.unpack_from("<i", cab, 42)[0]
    ot_end = 46 + nobjs * 20
    meta_tail = cab[ot_end : 20 + meta_sz]
    if bundle_name == "base_weapon_monster":
        meta_tail = (
            b"\x02\x00\x00\x00"
            + b"\x00" * 21
            + b"cab-base_uniform_entities\x00"
            + b"\x00" * 21
            + b"cab-base_uniform_shaders\x00\x00"
        )

    objs = []
    by_pid: Dict[int, Tuple[int, bytes]] = {}
    gos: Dict[int, str] = {}
    transforms: Dict[int, Tuple[int, List[int], int]] = {}
    p = 46
    for _ in range(nobjs):
        pid, off, sz, tid, cid, unk = struct.unpack_from("<iiiihh", cab, p)
        p += 20
        o = data_off + off
        d = bytes(cab[o : o + sz])
        objs.append([pid, off, sz, tid, cid, unk, d])
        by_pid[pid] = (cid, d)
        if cid == 1:
            nc = struct.unpack_from("<i", d, 0)[0]
            gp = 4 + nc * 12 + 4
            nl = struct.unpack_from("<i", d, gp)[0]
            gos[pid] = d[gp + 4 : gp + 4 + nl].decode("utf-8", "replace")
        elif cid == 4:
            gpid = struct.unpack_from("<i", d, 4)[0]
            nch = struct.unpack_from("<i", d, 48)[0]
            ch = [struct.unpack_from("<i", d, 52 + k * 8 + 4)[0] for k in range(nch)]
            par = struct.unpack_from("<i", d, 52 + nch * 8 + 4)[0]
            transforms[pid] = (gpid, ch, par)

    # Pre-build bone leaf CRC -> full path CRC maps per character directory when AnimationClips (cid=74) exist
    dir_lmap: Dict[str, Dict[int, int]] = {}
    dir_clips: Dict[int, str] = {}
    global_lmap: Dict[int, int] = {}
    if any(item[4] == 74 for item in objs):
        def _transform_lmap(root_tpid: int) -> Dict[int, int]:
            lmap: Dict[int, int] = {}
            _, ch, _ = transforms[root_tpid]
            stack = [(c, gos.get(transforms[c][0], "")) for c in ch if c in transforms]
            while stack:
                cur_t, cur_path = stack.pop()
                cgpid, cch, _ = transforms[cur_t]
                leaf = gos.get(cgpid, "")
                lmap[zlib.crc32(leaf.encode("utf-8"))] = zlib.crc32(cur_path.encode("utf-8"))
                for cc in cch:
                    if cc in transforms:
                        stack.append((cc, cur_path + "/" + gos.get(transforms[cc][0], "")))
            return lmap

        ab_List = [item[6] for item in objs if item[4] == 142]
        if ab_List:
            ab_d = ab_List[0]
            ap = 0
            nl = struct.unpack_from("<I", ab_d, ap)[0]
            ap = (4 + nl + 3) & ~3
            npre = struct.unpack_from("<I", ab_d, ap)[0]
            ap += 4
            pre = [struct.unpack_from("<ii", ab_d, ap + i * 8)[1] for i in range(npre)]
            ap += npre * 8
            ncnt = struct.unpack_from("<I", ab_d, ap)[0]
            ap += 4
            for _ in range(ncnt):
                kl = struct.unpack_from("<I", ab_d, ap)[0]
                k = ab_d[ap + 4 : ap + 4 + kl].decode("utf-8")
                ap = ((ap + 4 + kl + 3) & ~3) + 16
                fi, fsz = struct.unpack_from("<ii", ab_d, ap - 16)
                parts = k.split("/")
                if len(parts) >= 4 and parts[0] == "assets" and parts[1] == "characters":
                    cdir = "/".join(parts[:4])
                    lmap = dir_lmap.setdefault(cdir, {})
                    for p_pid in pre[fi : fi + fsz]:
                        if p_pid not in by_pid:
                            continue
                        ocid, od = by_pid[p_pid]
                        if ocid == 90:
                            m = _avatar_lmap(od)
                            lmap.update(m)
                            global_lmap.update(m)
                        elif ocid == 4 and transforms[p_pid][2] == 0:
                            m = _transform_lmap(p_pid)
                            lmap.update(m)
                            global_lmap.update(m)
                        elif ocid == 74:
                            dir_clips.setdefault(p_pid, cdir)

    added_objs = []
    for item in objs:
        pid, off, sz, tid, cid, unk, d = item
        if cid == 21:  # Material: insert m_CustomRenderQueue (-1) after m_ShaderKeywords
            nl = struct.unpack_from("<I", d, 0)[0]
            pos = ((4 + nl + 3) & ~3) + 8
            if bundle_name == "base_weapon_monster" and struct.unpack_from("<ii", d, pos - 8) == (1, 375229641):
                d = d[: pos - 8] + struct.pack("<i", 2) + d[pos - 4 :]
            kw_cnt = struct.unpack_from("<I", d, pos)[0]
            pos += 4
            for _ in range(kw_cnt):
                kl = struct.unpack_from("<I", d, pos)[0]
                pos = (pos + 4 + kl + 3) & ~3
            if bundle_name == "base_weapon_monster":
                t_pos = pos
                tex_cnt = struct.unpack_from("<I", d, t_pos)[0]
                t_pos += 4
                d_ba = bytearray(d)
                for _ in range(tex_cnt):
                    tl = struct.unpack_from("<I", d_ba, t_pos)[0]
                    t_pos = (t_pos + 4 + tl + 3) & ~3
                    if struct.unpack_from("<ii", d_ba, t_pos) == (1, 53064203):
                        struct.pack_into("<i", d_ba, t_pos, 2)
                    t_pos += 24
                d = bytes(d_ba)
            d = d[:pos] + b"\xff\xff\xff\xff" + d[pos:]
        elif cid == 23:  # MeshRenderer: append m_SortingLayerID (4B) + m_SortingOrder (4B)
            d = d + b"\x00" * 8
        elif cid == 29:  # SceneSettings: 16B -> 12B
            d = b"\x00" * 12
        elif cid == 43:  # Mesh: 4.2.1f4 -> 4.6.1p5 layout
            nl = struct.unpack_from("<I", d, 0)[0]
            pos = (4 + nl + 3) & ~3
            se = pos + 4 + struct.unpack_from("<I", d, pos)[0] * 44
            idx_sz = struct.unpack_from("<I", d, se + 16)[0]
            idx_end = se + 20 + ((idx_sz + 3) & ~3)
            skin_cnt = struct.unpack_from("<I", d, idx_end)[0]
            skin_end = idx_end + 4 + skin_cnt * 32
            bp_cnt = struct.unpack_from("<I", d, skin_end)[0]
            bp_end = skin_end + 4 + bp_cnt * 64
            d = (
                d[:se]
                + b"\x00" * 16
                + d[skin_end:bp_end]
                + struct.pack("<I", bp_cnt)
                + b"\x00" * (bp_cnt * 4 + 4)
                + d[se + 8 : skin_end]
                + d[bp_end:]
            )
        elif cid == 48 and obb_shaders and pid in obb_shaders:  # Shader: replace iOS 4.2 shader with Android 4.6 shader
            d = obb_shaders[pid]
        elif cid == 74:  # AnimationClip: 4.2.1f4 -> 4.6.1p5 (Legacy or Mecanim MuscleClip + ClipBindingConstant)
            nl = struct.unpack_from("<I", d, 0)[0]
            pos = (4 + nl + 3) & ~3
            if struct.unpack_from("<I", d, pos)[0] == 1:
                d = (
                    d[: pos + 5]
                    + b"\x01"
                    + d[pos + 6 : -1726]
                    + b"\x00\x00\x00\x00"
                    + d[-1726:-600]
                    + b"\x00" * 8
                    + d[-596:-13]
                    + d[-10:]
                    + b"\x00" * 7
                )
            else:
                lmap = dir_lmap.get(dir_clips.get(pid, ""), global_lmap)
                head_a = d[: pos + 8]
                head_b = d[pos + 8 : pos + 60]
                old_mc_sz = struct.unpack_from("<I", d, pos + 60)[0]
                mc_start = pos + 64
                delta_pose_bytes = d[mc_start : mc_start + 1072]
                p = mc_start + 1072
                sc_cnt = struct.unpack_from("<I", d, p)[0]
                sc_bytes = d[p : p + 8 + sc_cnt * 4]
                p += 8 + sc_cnt * 4
                fc, cc, sr, bt, sa_cnt = struct.unpack_from("<IIffI", d, p)
                dc_bytes = struct.pack("<IIffI", fc, cc, sr, 0.0 if fc == 0 else bt, sa_cnt) + d[p + 20 : p + 20 + sa_cnt * 4]
                p += 20 + sa_cnt * 4
                va_cnt = struct.unpack_from("<I", d, p)[0]
                b1 = [struct.unpack_from("<IIII", d, p + 4 + i * 16) for i in range(va_cnt)]
                p += 4 + va_cnt * 16
                times_6 = d[p : p + 24]
                p += 24
                idx_cnt = struct.unpack_from("<I", d, p)[0]
                idx_bytes = d[p : p + 4 + idx_cnt * 4]
                p += 4 + idx_cnt * 4
                add_cnt = struct.unpack_from("<I", d, p)[0]
                p += 4 + add_cnt * 4
                vad_cnt = struct.unpack_from("<I", d, p)[0]
                vad_bytes = d[p : p + 4 + vad_cnt * 8]
                p += 4 + vad_cnt * 8
                bools_12 = d[p : p + 12]
                new_bools_12 = bools_12[:2] + b"\x00" + bools_12[2:9] + b"\x00\x00"
                p += 12
                events_bytes = d[p:]

                gb = []
                i = 0
                while i < va_cnt:
                    bid, btype, _, _ = b1[i]
                    if btype == 0:
                        if bid in _ROOT_ANIM_IDS:
                            gb.append(struct.pack("<IIiiHBB", 0, _ROOT_ANIM_IDS[bid], 0, 0, 95, 8, 0))
                        else:
                            gb.append(struct.pack("<IIiiHBB", 0, bid, 0, 0, 95, 0, 0))
                        i += 1
                    else:
                        full_crc = lmap.get(bid, bid)
                        if btype == 0xF8D29E9F:
                            gb.append(struct.pack("<IIiiHBB", full_crc, 1, 0, 0, 4, 0, 0))
                            i += 3
                        elif btype == 0x83D85A86:
                            gb.append(struct.pack("<IIiiHBB", full_crc, 2, 0, 0, 4, 0, 0))
                            i += 4
                        else:
                            gb.append(struct.pack("<IIiiHBB", full_crc, 3, 0, 0, 4, 0, 0))
                            i += 3

                mc_new = (
                    delta_pose_bytes
                    + sc_bytes
                    + dc_bytes
                    + b"\x00\x00\x00\x00"
                    + b"\x00\x00\x00\x00"
                    + times_6
                    + idx_bytes
                    + vad_bytes
                    + new_bools_12
                )
                new_mc_sz = old_mc_sz - va_cnt * 16
                cbc_bytes = struct.pack("<I", len(gb)) + b"".join(gb) + b"\x00\x00\x00\x00"
                d = head_a + b"\x00\x00\x00\x00" + head_b + struct.pack("<I", new_mc_sz) + mc_new + cbc_bytes + events_bytes
        elif cid == 90:  # Avatar: 4.2.1f4 -> 4.6.1p5 full-path skeleton IDs + DefaultPose + RootMotionSkeleton
            nl = struct.unpack_from("<I", d, 0)[0]
            pos = (4 + nl + 3) & ~3
            name_bytes = d[:pos]
            av_sz = struct.unpack_from("<I", d, pos)[0]
            pos += 4
            n_cnt = struct.unpack_from("<I", d, pos)[0]
            pos += 4
            nodes_bytes = d[pos : pos + n_cnt * 8]
            nodes = [struct.unpack_from("<ii", d, pos + i * 8) for i in range(n_cnt)]
            pos += n_cnt * 8
            id_cnt = struct.unpack_from("<I", d, pos)[0]
            pos += 4
            ids = list(struct.unpack_from(f"<{id_cnt}I", d, pos))
            pos += id_cnt * 4
            ax_cnt = struct.unpack_from("<I", d, pos)[0]
            axes_bytes = d[pos : pos + 4 + ax_cnt * 80]
            pos += 4 + ax_cnt * 80
            xp_cnt = struct.unpack_from("<I", d, pos)[0]
            pose_bytes = d[pos : pos + 4 + xp_cnt * 48]
            pos += 4 + xp_cnt * 48
            human_bytes = d[pos : pos + 536]
            pos += 536
            hsi_cnt = struct.unpack_from("<I", d, pos)[0]
            hsi_bytes = d[pos : pos + 4 + hsi_cnt * 4]
            pos += 4 + hsi_cnt * 4
            rm_bytes = d[pos : pos + 52]
            pos += 52
            tos_cnt = struct.unpack_from("<I", d, pos)[0]
            pos += 4
            tos = {}
            for _ in range(tos_cnt):
                k, sl = struct.unpack_from("<II", d, pos)
                pos += 8
                tos[k] = d[pos : pos + sl].decode("utf-8")
                pos = (pos + sl + 3) & ~3
            full_paths = [""] * n_cnt
            full_ids = [0] * n_cnt
            for i in range(1, n_cnt):
                par = nodes[i][0]
                bname = tos[ids[i]]
                full_paths[i] = bname if par <= 0 else f"{full_paths[par]}/{bname}"
                full_ids[i] = zlib.crc32(full_paths[i].encode("utf-8"))
            skel_name_ids = [0] + ids[1:]
            tos_items = [(0, "")] + sorted((full_ids[i], full_paths[i]) for i in range(1, n_cnt))
            tos_buf = bytearray(struct.pack("<I", len(tos_items)))
            for k, v in tos_items:
                vb = v.encode("utf-8")
                tos_buf.extend(struct.pack("<II", k, len(vb)) + vb)
                while len(tos_buf) % 4 != 0:
                    tos_buf.append(0)
            rm_idx = struct.unpack_from("<i", rm_bytes, 0)[0]
            rm_new = (
                struct.pack("<IiiiiIII", 2, -1, -1, 0, -1, 2, 0, full_ids[rm_idx] if 0 < rm_idx < n_cnt else 0)
                + b"\x00" * 8
                + struct.pack("<III", 2, 0, rm_idx)
            )
            d = (
                name_bytes
                + struct.pack("<I", av_sz + n_cnt * 52 + 144)
                + struct.pack("<I", n_cnt)
                + nodes_bytes
                + struct.pack(f"<I{n_cnt}I", n_cnt, *full_ids)
                + axes_bytes
                + pose_bytes
                + pose_bytes
                + struct.pack(f"<I{n_cnt}I", n_cnt, *skel_name_ids)
                + human_bytes
                + b"\x00\x00\x00\x00"
                + hsi_bytes
                + rm_bytes
                + rm_new
                + bytes(tos_buf)
            )
        elif cid == 91:  # AnimatorController: 4.2.1f4 -> 4.6.1p5
            nl = struct.unpack_from("<I", d, 0)[0]
            pos = (4 + nl + 3) & ~3
            name_bytes = d[:pos]
            ctrl_sz = struct.unpack_from("<I", d, pos)[0]
            pos += 4
            p = pos
            lay_cnt = struct.unpack_from("<I", d, p)[0]
            p += 4
            for _ in range(lay_cnt):
                p += 16
                sk_cnt = struct.unpack_from("<I", d, p)[0]
                p += 4 + sk_cnt * 8 + 16
            layers_end = p
            sm_cnt = struct.unpack_from("<I", d, p)[0]
            p += 4
            p_scan = p
            for _ in range(sm_cnt):
                st_cnt = struct.unpack_from("<I", d, p_scan)[0]
                p_scan += 4
                for _ in range(st_cnt):
                    tr_cnt = struct.unpack_from("<I", d, p_scan)[0]
                    p_scan += 4
                    for _ in range(tr_cnt):
                        c_cnt = struct.unpack_from("<I", d, p_scan)[0]
                        p_scan += 4 + c_cnt * 16 + 24
                    bti_cnt = struct.unpack_from("<I", d, p_scan)[0]
                    p_scan += 4 + bti_cnt * 4
                    lf_cnt = struct.unpack_from("<I", d, p_scan)[0]
                    p_scan += 4
                    for _ in range(lf_cnt):
                        id_cnt = struct.unpack_from("<I", d, p_scan)[0]
                        p_scan += 4 + id_cnt * 4 + 4
                    bt_cnt = struct.unpack_from("<I", d, p_scan)[0]
                    p_scan += 4
                    for _ in range(bt_cnt):
                        nd_cnt = struct.unpack_from("<I", d, p_scan)[0]
                        p_scan += 4
                        for _ in range(nd_cnt):
                            p_scan += 12
                            ch_cnt = struct.unpack_from("<I", d, p_scan)[0]
                            p_scan += 4 + ch_cnt * 4
                            th_cnt = struct.unpack_from("<I", d, p_scan)[0]
                            p_scan += 4 + th_cnt * 4
                            c1 = struct.unpack_from("<I", d, p_scan)[0]
                            p_scan += 4 + c1 * 8
                            c2 = struct.unpack_from("<I", d, p_scan)[0]
                            p_scan += 4 + c2 * 4
                            c3 = struct.unpack_from("<I", d, p_scan)[0]
                            p_scan += 4
                            for _ in range(c3):
                                nc = struct.unpack_from("<I", d, p_scan)[0]
                                p_scan += 4 + nc * 4
                            c4 = struct.unpack_from("<I", d, p_scan)[0]
                            p_scan += 4 + c4 * 4
                            c5 = struct.unpack_from("<I", d, p_scan)[0]
                            p_scan += 4 + c5 * 4
                            p_scan += 16
                        ev_cnt = struct.unpack_from("<I", d, p_scan)[0]
                        p_scan += 4 + ev_cnt * 4
                    p_scan += 20
                any_cnt = struct.unpack_from("<I", d, p_scan)[0]
                p_scan += 4
                for _ in range(any_cnt):
                    c_cnt = struct.unpack_from("<I", d, p_scan)[0]
                    p_scan += 4 + c_cnt * 16 + 24
                p_scan += 8
            sm_end = p_scan
            v_cnt = struct.unpack_from("<I", d, p_scan)[0]
            p_scan += 4 + v_cnt * 16
            for elem_sz in (1, 4, 4, 16):
                c_cnt = struct.unpack_from("<I", d, p_scan)[0]
                p_scan = (p_scan + 4 + c_cnt * elem_sz + 3) & ~3
            dv_end = p_scan
            tos_cnt = struct.unpack_from("<I", d, p_scan)[0]
            p_scan += 4
            tos = {3258172340: "DynamicCurve"}
            for _ in range(tos_cnt):
                k, sl = struct.unpack_from("<II", d, p_scan)
                p_scan += 8
                tos[k] = d[p_scan : p_scan + sl].decode("utf-8")
                p_scan = (p_scan + sl + 3) & ~3
            clips_bytes = d[p_scan:]

            sm_buf = bytearray(struct.pack("<I", sm_cnt))
            p = layers_end + 4
            leaf_idx = 0
            for _ in range(sm_cnt):
                st_cnt = struct.unpack_from("<I", d, p)[0]
                p += 4
                sm_buf.extend(struct.pack("<I", st_cnt))
                for _ in range(st_cnt):
                    tr_cnt = struct.unpack_from("<I", d, p)[0]
                    p += 4
                    sm_buf.extend(struct.pack("<I", tr_cnt))
                    for _ in range(tr_cnt):
                        c_cnt = struct.unpack_from("<I", d, p)[0]
                        tr_len = 4 + c_cnt * 16 + 24
                        tr_b = bytearray(d[p : p + tr_len])
                        tr_b[-3] = 1
                        sm_buf.extend(tr_b)
                        p += tr_len
                    bti_cnt = struct.unpack_from("<I", d, p)[0]
                    sm_buf.extend(d[p : p + 4 + bti_cnt * 4])
                    p += 4 + bti_cnt * 4
                    lf_cnt = struct.unpack_from("<I", d, p)[0]
                    p += 4
                    sm_buf.extend(struct.pack("<I", lf_cnt))
                    for _ in range(lf_cnt):
                        id_cnt = struct.unpack_from("<I", d, p)[0]
                        sm_buf.extend(d[p : p + 4 + id_cnt * 4] + struct.pack("<I", leaf_idx))
                        leaf_idx += 1
                        p += 4 + id_cnt * 4 + 4
                    bt_cnt = struct.unpack_from("<I", d, p)[0]
                    p += 4
                    sm_buf.extend(struct.pack("<I", bt_cnt))
                    for _ in range(bt_cnt):
                        nd_cnt = struct.unpack_from("<I", d, p)[0]
                        p += 4
                        sm_buf.extend(struct.pack("<I", nd_cnt))
                        for _ in range(nd_cnt):
                            p_nd = p
                            p += 12
                            ch_cnt = struct.unpack_from("<I", d, p)[0]
                            p += 4 + ch_cnt * 4
                            th_cnt = struct.unpack_from("<I", d, p)[0]
                            p += 4 + th_cnt * 4
                            c1 = struct.unpack_from("<I", d, p)[0]
                            p += 4 + c1 * 8
                            c2 = struct.unpack_from("<I", d, p)[0]
                            p += 4 + c2 * 4
                            c3 = struct.unpack_from("<I", d, p)[0]
                            p += 4
                            for _ in range(c3):
                                nc = struct.unpack_from("<I", d, p)[0]
                                p += 4 + nc * 4
                            c4 = struct.unpack_from("<I", d, p)[0]
                            p += 4 + c4 * 4
                            c5 = struct.unpack_from("<I", d, p)[0]
                            p += 4 + c5 * 4
                            sm_buf.extend(d[p_nd:p])
                            sm_buf.extend(d[p : p + 4] + b"\xff\xff\xff\xff\x00\x00\x80\x3f" + d[p + 8 : p + 16])
                            p += 16
                        ev_cnt = struct.unpack_from("<I", d, p)[0]
                        p += 4 + ev_cnt * 4
                    path_id = struct.unpack_from("<I", d, p)[0]
                    leaf = tos.get(path_id, "").split(".")[-1]
                    name_id = zlib.crc32(leaf.encode("utf-8")) if leaf else path_id
                    if leaf:
                        tos[name_id] = leaf
                    sm_buf.extend(struct.pack("<I", name_id) + d[p : p + 20])
                    p += 20
                any_cnt = struct.unpack_from("<I", d, p)[0]
                p += 4
                sm_buf.extend(struct.pack("<I", any_cnt))
                for _ in range(any_cnt):
                    c_cnt = struct.unpack_from("<I", d, p)[0]
                    tr_len = 4 + c_cnt * 16 + 24
                    tr_b = bytearray(d[p : p + tr_len])
                    tr_b[-3] = 1
                    sm_buf.extend(tr_b)
                    p += tr_len
                sm_buf.extend(d[p : p + 8])
                p += 8

            new_ctrl_sz = ctrl_sz + (28 if sm_cnt > 1 else 24)
            tos_items = sorted(tos.items())
            tos_buf = bytearray(struct.pack("<I", len(tos_items)))
            for k, v in tos_items:
                vb = v.encode("utf-8")
                tos_buf.extend(struct.pack("<II", k, len(vb)) + vb)
                while len(tos_buf) % 4 != 0:
                    tos_buf.append(0)
            d = (
                name_bytes
                + struct.pack("<I", new_ctrl_sz)
                + d[pos:layers_end]
                + bytes(sm_buf)
                + d[sm_end:dv_end]
                + b"\x00" * 8
                + bytes(tos_buf)
                + clips_bytes
            )
        elif cid == 95:  # Animator: 34B -> 42B
            d = d[:28] + struct.pack("<iiiBB", d[28], d[33], d[32], 1, 1)
        elif cid == 104:  # RenderSettings: insert m_AmbientIntensity = 3.0f before last 16B
            d = d[:-16] + b"\x00\x00\x40\x40" + d[-16:]
        elif cid == 111:  # Animation: 68B -> 44B
            d = d[:-24]
        elif cid == 114 and is_scene:
            if len(d) == 28:  # EnemySpot (28B -> 40B) and normalize _enemyType
                etype = struct.unpack_from("<i", d, 24)[0]
                new_etype = 4 if etype in (4, 5, 6) else 0
                tail = b"\x01\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00" if new_etype == 4 else b"\x00" * 12
                d = d[:24] + struct.pack("<i", new_etype) + tail
            elif len(d) == 104:
                gpid = struct.unpack_from("<i", d, 4)[0]
                if gos.get(gpid) == "trigger_manager":  # TriggerManager (104B -> 112B)
                    d = d[:24] + b"\x00\x00\x00\x00" + d[24:88] + b"\x00\x00\x00\x00" + d[88:]
        elif cid == 114 and not is_scene:
            spid = struct.unpack_from("<i", d, 16)[0]
            if spid == -1917628463:  # UIPanel: 144B -> 148B
                d = d[:24] + b"\x00\x00\x00\x00" + d[24:]
            elif spid == 1841472679:  # UIHPController: 64B -> 80B
                d = d[:-4] + b"\x00" * 8 + d[-4:] + b"\x00" * 8
            elif spid in (-466240514, 1579591672):  # UISprite / UIFilledSprite: -16B
                d = d[:24] + d[40:]
            elif spid == 327204354:  # UILabel: 152B -> 160B
                tl = struct.unpack_from("<I", d, 72)[0]
                tend = (76 + tl + 3) & ~3
                d = d[:24] + d[40 : tend + 4] + b"\x00" * 4 + d[tend + 4 : -12] + b"\x00" * 4 + b"\x00\x00\x80\x3f" * 4 + d[-12:]
            elif spid == -1652829759:  # AvatarController: +28B
                d = d + b"\x00" * 28
        elif cid == 137:  # SkinnedMeshRenderer: +12B
            mat_cnt = struct.unpack_from("<I", d, 28)[0]
            sub_pos = 32 + mat_cnt * 8
            sub_cnt = struct.unpack_from("<I", d, sub_pos)[0]
            ins1 = sub_pos + 4 + sub_cnt * 4 + 20
            ins2 = len(d) - 36
            d = d[:ins1] + b"\x00" * 8 + d[ins1:ins2] + b"\x00" * 4 + d[ins2:]
        elif cid == 142 and not is_scene:  # AssetBundle: add TextAsset index + 4.6.1p5 tail
            pos = 0
            nl = struct.unpack_from("<I", d, pos)[0]
            pos = (4 + nl + 3) & ~3
            npre_off = pos
            npre = struct.unpack_from("<I", d, pos)[0]
            pos += 4 + npre * 8
            pre_end = pos
            ncnt = struct.unpack_from("<I", d, pos)[0]
            pos += 4
            cnt_entries: List[Tuple[str, bytes]] = []
            xml_keys: List[str] = []
            for _ in range(ncnt):
                kl = struct.unpack_from("<I", d, pos)[0]
                k = d[pos + 4 : pos + 4 + kl].decode("utf-8")
                pos = (pos + 4 + kl + 3) & ~3
                ainfo = d[pos : pos + 16]
                pos += 16
                if bundle_name == "base_char_enemy0":
                    if any(x in k for x in ("/bat/", "/wolf/", "/zombie/")):
                        continue
                    cnt_entries.append((k, ainfo))
                    xml_keys.append(k)
                    for low_pref, mixed_prefs in _CHAR_DIR_CASE_MAP:
                        if k.startswith(low_pref):
                            rel = k[len(low_pref) :]
                            for mp in mixed_prefs:
                                xml_keys.append(mp + rel)
                            break
                elif bundle_name == "base_weapon_monster":
                    if any(x in k for x in ("_skeleton_", "_bat_", "_wolf_", "_zombie_")):
                        continue
                    fname = k.split("/")[-1]
                    sub = None
                    for pref, sd in _WEP_MONSTER_SUBDIRS:
                        if fname.startswith(pref):
                            sub = sd
                            break
                    if sub:
                        sub_low = f"assets/weapon/monster/{sub}/{fname}"
                        sub_mix = f"Assets/Weapon/Monster/{sub}/{fname}"
                        cnt_entries.append((sub_low, ainfo))
                        xml_keys.append(sub_low)
                        xml_keys.append(sub_mix)
                    else:
                        cnt_entries.append((k, ainfo))
                        xml_keys.append(k)
                else:
                    cnt_entries.append((k, ainfo))
                    xml_keys.append(k)

            ta_pid = 999999
            while ta_pid in by_pid:
                ta_pid += 1
            xml_lines = [
                f'<AssetBundle xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" Filename="{bundle_name}" Type="Asset" Compressed="false">',
                "\t<Assets>",
            ]
            for k in xml_keys:
                xml_lines.append(f'\t\t<Asset Filename="{k}" GUID="00000000000000000000000000000000" />')
            xml_lines.append("\t</Assets>")
            xml_lines.append("</AssetBundle>")
            xml_str = "\r\n".join(xml_lines)
            ta_bytes = _pack_str(bundle_name) + _pack_str(xml_str) + _pack_str("")
            added_objs.append([ta_pid, 0, len(ta_bytes), 49, 49, 0, ta_bytes])

            pre_raw = bytearray(d[npre_off + 4 : pre_end])
            if bundle_name == "base_weapon_monster":
                sh_pids = {-804261638, 53064203, 375229641, 786445147}
                for p_idx in range(npre):
                    pf, pp = struct.unpack_from("<ii", pre_raw, p_idx * 8)
                    if pf == 1 and pp in sh_pids:
                        struct.pack_into("<i", pre_raw, p_idx * 8, 2)
            new_pre = struct.pack("<I", npre + 1) + bytes(pre_raw) + struct.pack("<ii", 0, ta_pid)
            cnt_entries.append((bundle_name.lower(), struct.pack("<iiii", npre, 1, 0, ta_pid)))
            cnt_entries.sort(key=lambda x: x[0])
            cnt_buf = bytearray(struct.pack("<I", len(cnt_entries)))
            for k, ainfo in cnt_entries:
                cnt_buf += _pack_str(k) + ainfo
            d = d[:npre_off] + new_pre + bytes(cnt_buf) + b"\x00" * 24 + b"\x01\x00\x00\x00"
        elif cid == 142 and is_scene:  # Scene AssetBundle: clear 4.2.1f4 script/class compatibility hashes
            d = b"\x00" * 36 + b"\x01\x00\x00\x00"
        elif cid == 199:  # ParticleSystemRenderer: 128B -> 136B
            d = d[:-68] + b"\x00" * 8 + d[-68:]

        item[6] = d
        item[2] = len(d)

    all_objs = objs + added_objs
    order = list(range(len(objs)))
    order.sort(key=lambda i: objs[i][1])
    for i in range(len(objs), len(all_objs)):
        order.append(i)

    data_buf = bytearray()
    for i in order:
        while len(data_buf) % 8 != 0:
            data_buf.append(0)
        all_objs[i][1] = len(data_buf)
        data_buf.extend(all_objs[i][6])

    all_objs.sort(key=lambda x: x[0])
    new_nobjs = len(all_objs)
    new_meta_sz = 26 + new_nobjs * 20 + len(meta_tail)
    new_data_off = data_off if (new_nobjs == nobjs and new_meta_sz == meta_sz) else max(4096, (20 + new_meta_sz + 15) & ~15)

    ot_buf = bytearray()
    for pid, off, sz, tid, cid, unk, _ in all_objs:
        ot_buf.extend(struct.pack("<iiiihh", pid, off, sz, tid, cid, unk))

    hdr_prefix = (
        cab[16:20]
        + b"4.6.1p5\n1\x00"
        + struct.pack("<I", 13)
        + cab[34:42]
        + struct.pack("<i", new_nobjs)
        + ot_buf
        + meta_tail
    )
    assert len(hdr_prefix) == 4 + new_meta_sz
    pad_len = new_data_off - (16 + len(hdr_prefix))
    assert pad_len >= 0
    new_file_sz = new_data_off + len(data_buf)
    top_hdr = struct.pack(">IIII", new_meta_sz, new_file_sz, ver, new_data_off)
    return top_hdr + hdr_prefix + (b"\x00" * pad_len) + bytes(data_buf)


def convert_ipa_bundle(
    raw_bytes: bytes,
    bundle_name: str,
    is_scene: bool,
    obb_shaders: Optional[Dict[int, bytes]] = None,
) -> bytes:
    """Convert a v0.1.0 IPA AssetBundle (Unity 4.2.1f4 iOS) into an uncompressed UnityRaw 4.6.1p5 Android bundle."""
    p = raw_bytes.index(b"\x00", 12) + 1
    p = raw_bytes.index(b"\x00", p) + 1
    _, hdr_sz = struct.unpack_from(">II", raw_bytes, p)
    if raw_bytes.startswith(b"UnityWeb"):
        props = raw_bytes[hdr_sz : hdr_sz + 5]
        uncomp_size = struct.unpack("<Q", raw_bytes[hdr_sz + 5 : hdr_sz + 13])[0]
        filt = lzma._decode_filter_properties(lzma.FILTER_LZMA1, props)
        decomp = lzma.LZMADecompressor(lzma.FORMAT_RAW, None, [filt]).decompress(
            raw_bytes[hdr_sz + 13 :], max_length=uncomp_size
        )
    else:
        decomp = raw_bytes[hdr_sz:]

    num_files = struct.unpack_from(">I", decomp, 0)[0]
    p = 4
    files = []
    for _ in range(num_files):
        end = decomp.index(b"\x00", p)
        fname = decomp[p:end].decode("utf-8")
        p = end + 1
        foff, fsize = struct.unpack_from(">II", decomp, p)
        p += 8
        files.append((fname, foff, decomp[foff : foff + fsize]))

    first_foff = files[0][1]
    conv_files = []
    cur_off = first_foff
    for fname, _, cab in files:
        while cur_off % 4 != 0:
            cur_off += 1
        new_cab = _convert_serialized_file(cab, bundle_name, is_scene, obb_shaders=obb_shaders)
        conv_files.append((fname, cur_off, new_cab))
        cur_off += len(new_cab)

    dir_buf = bytearray(struct.pack(">I", len(conv_files)))
    for fname, foff, new_cab in conv_files:
        dir_buf.extend(fname.encode("utf-8") + b"\x00")
        dir_buf.extend(struct.pack(">II", foff, len(new_cab)))

    body = bytearray(dir_buf)
    for _, foff, new_cab in conv_files:
        while len(body) < foff:
            body.append(0)
        body.extend(new_cab)

    body_sz = len(body)
    total_sz = 60 + body_sz
    out_hdr = (
        b"UnityRaw\x00\x00\x00\x00\x033.x.x\x004.6.1p5\x00"
        + struct.pack(">IIIIIIII", total_sz, 60, 1, 1, body_sz, body_sz, total_sz, first_foff)
        + b"\x00"
    )
    assert len(out_hdr) == 60
    return out_hdr + bytes(body)


