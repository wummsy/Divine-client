"""Tests for Divine Client server collaborator access granting and permission management."""
import json
import os
import shutil
import tempfile
import time
import unittest

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server")))

from divineclient import web_server
import server.db as srv_db


class TestServerCollaboratorAccess(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="divine_test_collab_")
        self.orig_db = os.environ.get("DIVINE_DB")
        self.test_db_path = os.path.join(self.tmp_dir, "test_collab.db")
        os.environ["DIVINE_DB"] = self.test_db_path
        srv_db._conn = None
        srv_db.DB_PATH = self.test_db_path
        srv_db.init_db()

    def tearDown(self):
        if srv_db._conn:
            try:
                srv_db._conn.close()
            except Exception:
                pass
            srv_db._conn = None
        if self.orig_db:
            os.environ["DIVINE_DB"] = self.orig_db
        else:
            os.environ.pop("DIVINE_DB", None)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_local_server_access_json(self):
        """Test local access.json reading, writing, and auto-whitelisting."""
        sdir = os.path.join(self.tmp_dir, "server_1")
        os.makedirs(sdir, exist_ok=True)

        # Initial read should return empty users
        acc = web_server._read_server_access(sdir)
        self.assertEqual(acc.get("users"), [])

        # Write access data
        test_users = [
            {
                "username": "wummsy",
                "discord_id": "123456789012345678",
                "permissions": ["power", "console", "files", "players", "settings", "network"],
                "added_at": "2026-09-18 10:00:00"
            }
        ]
        web_server._write_server_access(sdir, {"users": test_users})

        # Read back
        acc2 = web_server._read_server_access(sdir)
        self.assertEqual(len(acc2.get("users")), 1)
        self.assertEqual(acc2["users"][0]["username"], "wummsy")
        self.assertIn("power", acc2["users"][0]["permissions"])
        self.assertIn("console", acc2["users"][0]["permissions"])

        # Auto-whitelist test
        wfile = os.path.join(sdir, "whitelist.json")
        with open(wfile, "w", encoding="utf-8") as f:
            json.dump([{"name": "owner", "uuid": ""}], f)

        web_server._auto_whitelist_user(sdir, "wummsy")
        with open(wfile, "r", encoding="utf-8") as f:
            wdata = json.load(f)
        names = [entry.get("name") for entry in wdata]
        self.assertIn("owner", names)
        self.assertIn("wummsy", names)

    def test_backend_collaborator_db(self):
        """Test backend database collaborator CRUD and permissions checks."""
        # Create user & game server
        srv_db.upsert_user("1001", "HostOwner", "https://avatar.png")
        srv_db.upsert_user("2002", "CollabUser", "https://avatar2.png")

        code = srv_db.create_server("1001", "Survival Realm", "127.0.0.1:25565", "1.21.4", "paper")
        self.assertTrue(code)

        # Grant collaborator access
        srv_db.add_server_collaborator(code, "2002", "CollabUser", ["power", "console", "files"])

        # Get collaborators
        collabs = srv_db.get_server_collaborators(code)
        self.assertEqual(len(collabs), 1)
        self.assertEqual(collabs[0]["username"], "CollabUser")
        self.assertEqual(collabs[0]["user_id"], "2002")
        self.assertIn("power", collabs[0]["permissions"])
        self.assertIn("console", collabs[0]["permissions"])
        self.assertNotIn("settings", collabs[0]["permissions"])

        # Test permission checks
        ok_owner, role = srv_db.check_server_permission(code, "1001")
        self.assertTrue(ok_owner)
        self.assertEqual(role, "owner")

        ok_power, _ = srv_db.check_server_permission(code, "2002", "power")
        self.assertTrue(ok_power)

        ok_console, _ = srv_db.check_server_permission(code, "2002", "console")
        self.assertTrue(ok_console)

        ok_settings, err = srv_db.check_server_permission(code, "2002", "settings")
        self.assertFalse(ok_settings)

        # Test shared servers for user
        shared = srv_db.get_shared_servers_for_user("2002")
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0]["code"], code)
        self.assertEqual(shared[0]["name"], "Survival Realm")

        # Test revoking collaborator access
        srv_db.remove_server_collaborator(code, "2002")
        collabs_after = srv_db.get_server_collaborators(code)
        self.assertEqual(len(collabs_after), 0)

        ok_after, _ = srv_db.check_server_permission(code, "2002", "power")
        self.assertFalse(ok_after)


if __name__ == "__main__":
    unittest.main()
