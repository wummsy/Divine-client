"""Tests for Discord bot /getcode and database device lookup features."""
import os
import sys
import unittest
import tempfile
import time
from unittest.mock import MagicMock

if "discord" not in sys.modules:
    class MockField:
        def __init__(self, name, value, inline=False):
            self.name = name
            self.value = value
            self.inline = inline

    class MockEmbed:
        def __init__(self, **kwargs):
            self.title = kwargs.get("title", "")
            self.description = kwargs.get("description", "")
            self.fields = []
        def add_field(self, **kwargs):
            self.fields.append(MockField(kwargs.get("name", ""), kwargs.get("value", ""), kwargs.get("inline", False)))
        def set_thumbnail(self, **kwargs):
            pass
        def set_footer(self, **kwargs):
            pass

    mock_discord = MagicMock()
    mock_discord.Embed = MockEmbed
    mock_discord.utils.utcnow = lambda: 0
    mock_discord.Color = MagicMock()
    mock_discord.__path__ = []
    sys.modules["discord"] = mock_discord
    sys.modules["discord.app_commands"] = MagicMock()
    sys.modules["discord.ext"] = MagicMock()
    sys.modules["discord.ext.tasks"] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import db

class TestBotDeviceLookup(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_file = os.path.join(self.tmp_dir.name, "test_divine.db")
        os.environ["DIVINE_DB"] = self.db_file
        db.DB_PATH = self.db_file
        db._conn = None
        db.init_db()

    def tearDown(self):
        if db._conn:
            db._conn.close()
            db._conn = None
        self.tmp_dir.cleanup()

    def test_lookup_user_by_name_and_device(self):
        # 1. Register a user
        db.upsert_user("123456789012345678", "steve_builder", "https://example.com/steve.png")
        
        # 2. Record device activity
        dev1 = "DEV-A1B2-C3D4-E5F6-7890"
        dev2 = "DEV-9988-7766-5544-3322"
        db.record_device_activity(dev1, user_id="123456789012345678")
        time.sleep(0.01)
        db.record_device_activity(dev2, user_id="123456789012345678")

        # 3. Lookup by exact username
        res = db.lookup_device_info("steve_builder")
        self.assertIsNotNone(res)
        self.assertEqual(res["user_id"], "123456789012345678")
        self.assertEqual(res["username"], "steve_builder")
        self.assertEqual(len(res["devices"]), 2)
        dev_codes = [d["device_code"] for d in res["devices"]]
        self.assertIn(dev1, dev_codes)
        self.assertIn(dev2, dev_codes)
        self.assertFalse(res["banned"])

        # 4. Lookup by Discord mention
        res_mention = db.lookup_device_info("<@123456789012345678>")
        self.assertIsNotNone(res_mention)
        self.assertEqual(res_mention["username"], "steve_builder")

        # 5. Lookup by user ID
        res_id = db.lookup_device_info("123456789012345678")
        self.assertIsNotNone(res_id)
        self.assertEqual(res_id["username"], "steve_builder")

        # 6. Lookup directly by device code
        res_dev = db.lookup_device_info(dev1)
        self.assertIsNotNone(res_dev)
        self.assertEqual(res_dev["query_type"], "device")
        self.assertEqual(res_dev["device_code"], dev1)
        self.assertEqual(len(res_dev["associated_users"]), 1)
        self.assertEqual(res_dev["associated_users"][0]["id"], "123456789012345678")

    def test_lookup_banned_user_and_device(self):
        uid = "555555555555555555"
        uname = "bad_actor"
        dcode = "DEV-DEAD-BEEF-CAFE-0001"
        
        db.upsert_user(uid, uname, "")
        db.record_device_activity(dcode, user_id=uid)
        
        # Ban user
        ok, msg = db.ban_user(uname, reason="Cheating", banned_by="ModAdmin (999)")
        self.assertTrue(ok)

        # Lookup by username
        res = db.lookup_device_info(uname)
        self.assertIsNotNone(res)
        self.assertTrue(res["banned"])
        self.assertEqual(res["devices"][0]["device_code"], dcode)
        self.assertTrue(res["devices"][0]["banned"])
        self.assertEqual(res["devices"][0]["ban_reason"], "Cheating")

        # Lookup by device code
        res_dev = db.lookup_device_info(dcode)
        self.assertIsNotNone(res_dev)
        self.assertTrue(res_dev["banned"])
        self.assertEqual(res_dev["ban_info"]["reason"], "Cheating")

    def test_unregistered_lookup(self):
        res = db.lookup_device_info("non_existent_player_12345")
        self.assertIsNone(res)

    def test_live_player_stats_and_panel(self):
        # 1. Register users
        db.upsert_user("1001", "alex_gamer", "")
        db.upsert_user("1002", "steve_crafter", "")
        db.upsert_user("1003", "offline_user", "")

        # 2. Set live presence
        db.set_presence("1001", "in_game", "Playing 1.21.4 (Fabric)")
        db.set_presence("1002", "online", "In launcher menus")
        db.set_presence("1003", "offline", "")

        # 3. Query stats
        stats = db.get_live_player_stats()
        self.assertEqual(stats["total_registered"], 3)
        self.assertEqual(stats["total_online"], 2)
        self.assertEqual(stats["playing_count"], 1)
        self.assertEqual(stats["in_launcher_count"], 1)
        self.assertEqual(stats["total_offline"], 1)
        self.assertEqual(stats["playing_users"][0]["username"], "alex_gamer")
        self.assertEqual(stats["in_launcher_users"][0]["username"], "steve_crafter")

        # 4. Verify bot embed builder
        import bot
        embed = bot._build_live_player_panel_embed(stats)
        self.assertIn("Live Player & Network Panel", embed.title)
        self.assertIn("2", embed.description)
        self.assertTrue(any("Launcher Activity" in f.name for f in embed.fields))
        self.assertTrue(any("Currently In-Game" in f.name for f in embed.fields))
        self.assertTrue(any("In Launcher Menus" in f.name for f in embed.fields))

    def test_redemption_codes_and_profile_audit(self):
        # 1. Generate single-use redemption code
        code = db.create_redeem_code(product_id="server_slot", created_by="Admin-999")
        self.assertTrue(code.startswith("AREV-"))
        
        info = db.get_code_info(code)
        self.assertIsNotNone(info)
        self.assertEqual(info["product_id"], "server_slot")
        self.assertIsNone(info["redeemed_at"])
        self.assertFalse(info["is_revoked"])

        # 2. Redeem code for player
        res = db.redeem_code(code, user_id="1001", username="alex_gamer", device_code="DEV-ALEX-1122-3344")
        self.assertTrue(res["success"])
        self.assertEqual(res["product_id"], "server_slot")

        # 3. Double-redemption must be rejected
        res_double = db.redeem_code(code, user_id="1002", username="steve_crafter", device_code="DEV-STEVE-5566-7788")
        self.assertFalse(res_double["success"])
        self.assertTrue(res_double.get("already_redeemed"))

        # 4. Check user redeemed codes list
        user_codes = db.get_user_redeemed_codes("1001")
        self.assertEqual(len(user_codes), 1)
        self.assertEqual(user_codes[0]["code"], code)

        # 5. Check audit log event was created
        logs = db.get_connection_logs(limit=5)
        self.assertTrue(any(f"code_redeemed:server_slot:{code}" in (l.get("event_type") or "") for l in logs))

        # 6. Revoke code test
        code2 = db.create_redeem_code(product_id="cosmetics_vip", created_by="Admin-999")
        revoked_ok = db.revoke_code(code2, revoked_by="Admin-999")
        self.assertTrue(revoked_ok)

        # Redeeming revoked code must be rejected
        res_revoked = db.redeem_code(code2, user_id="1001", username="alex_gamer")
        self.assertFalse(res_revoked["success"])
        self.assertIn("revoked", res_revoked["error"])

    def test_bot_serverlist_and_clearserver(self):
        # 1. Register users and servers
        db.upsert_user("2001", "host_master", "")
        db.upsert_user("2002", "player_two", "")
        
        code1 = db.create_server("2001", "Master SMP", "relay.divineclient.net:25565", "1.21.1", "paper")
        code2 = db.create_server("2001", "Fabric Fun", "relay.divineclient.net:25566", "1.21.4", "fabric")
        code3 = db.create_server("2002", "Player2 Realm", "playit.gg:12345", "1.20.1", "purpur")

        # 2. List all game servers
        all_servers = db.list_all_game_servers()
        self.assertEqual(len(all_servers), 3)

        # 3. List specific user servers
        user_servers = db.list_all_game_servers(host_id="2001")
        self.assertEqual(len(user_servers), 2)
        codes = [s["code"] for s in user_servers]
        self.assertIn(code1, codes)
        self.assertIn(code2, codes)

        # 4. Clear user servers
        db.clear_user_servers("2001")
        self.assertEqual(len(db.list_all_game_servers(host_id="2001")), 0)
        self.assertEqual(len(db.list_all_game_servers()), 1)

        # 5. Clear all servers
        db.clear_all_servers()
        self.assertEqual(len(db.list_all_game_servers()), 0)

if __name__ == "__main__":
    unittest.main()
