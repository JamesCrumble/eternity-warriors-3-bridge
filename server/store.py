"""Player accounts and their Gluon attributes, kept in one JSON file.

An attribute is what the game calls its save: PlayerInfoManager writes
mage_basic, warrior_inventory, ... as (name, value) pairs through SetAttributes
and reads them back with GetAttributes. Values are stored exactly as sent.
"""
import json
import os
import threading
import uuid


class Store:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "players.json")
        self.lock = threading.RLock()
        self.data = {"players": {}}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)

    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)

    def players(self):
        return self.data["players"]

    def login(self, login_id, create=True):
        """Returns the player record for a device login id, creating it on first sight."""
        with self.lock:
            for pid, p in self.players().items():
                if p["loginId"] == login_id:
                    return pid, p
            if not create:
                return None, None
            pid = uuid.uuid4().hex
            p = {"loginId": login_id, "nickName": "", "attributes": {}, "cgs": {}}
            self.players()[pid] = p
            self.save()
            return pid, p

    def get(self, pid):
        return self.players().get(pid)

    def set_attributes(self, pid, attrs):
        with self.lock:
            p = self.players()[pid]
            for a in attrs:
                p["attributes"][a["name"]] = a.get("value")
            self.save()

    def get_attributes(self, pid, names=None):
        p = self.players().get(pid) or {"attributes": {}}
        items = p["attributes"].items()
        return [{"name": k, "value": v} for k, v in items if not names or k in names]

    def delete_attributes(self, pid):
        with self.lock:
            self.players()[pid]["attributes"] = {}
            self.save()
