import unittest
import json
import os
import time

from divineclient.core import ingame_bridge
from divineclient import web_server


class TestInGameModBridgeAndCosmetics(unittest.TestCase):
    def setUp(self):
        ingame_bridge.save_redeemed_codes([])
        ingame_bridge.save_generated_codes({})
        self.app = web_server.app.test_client()

    def test_load_mods_config_contains_all_qol_mods(self):
        mods = ingame_bridge.load_mods_config()
        self.assertIn("fps_display", mods)
        self.assertIn("coordinates", mods)
        self.assertIn("cinematic_zoom", mods)
        self.assertIn("fullbright_gamma", mods)
        self.assertNotIn("hypixel_mods", mods)
        self.assertNotIn("hypixel_quickplay", mods)
        self.assertIn("scoreboard_customizer", mods)
        self.assertIn("block_overlay", mods)
        self.assertIn("armor_warning", mods)
        self.assertIn("chat_tweaks", mods)
        self.assertIn("memory_hud", mods)
        self.assertIn("attack_cooldown", mods)
        self.assertIn("item_counter", mods)
        self.assertIn("nick_hider", mods)
        self.assertIn("particle_changer", mods)
        self.assertIn("uhc_overlay", mods)
        self.assertIn("keystrokes", mods)
        self.assertIn("armor_status", mods)
        self.assertIn("potion_effects", mods)
        self.assertIn("divine_nametags", mods)
        self.assertIn("low_fire", mods)
        self.assertIn("small_totem", mods)

    def test_toggle_mod_api(self):
        r = self.app.post("/api/ingame/mods/fps_display/toggle", json={"enabled": False})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json["mod"]["enabled"])

        r = self.app.post("/api/ingame/mods/fps_display/toggle", json={"enabled": True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["mod"]["enabled"])

        # Test new QoL mods toggles
        r = self.app.post("/api/ingame/mods/scoreboard_customizer/toggle", json={"enabled": True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["mod"]["enabled"])

        r = self.app.post("/api/ingame/mods/armor_warning/toggle", json={"enabled": True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["mod"]["enabled"])

        r = self.app.post("/api/ingame/mods/memory_hud/toggle", json={"enabled": True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["mod"]["enabled"])

    def test_cosmetics_catalog_and_redeem(self):
        r = self.app.get("/api/ingame/cosmetics")
        self.assertEqual(r.status_code, 200)
        data = r.json
        self.assertIn("cloaks", data["categories"])
        self.assertIn("wings", data["categories"])
        self.assertIn("halos", data["categories"])
        self.assertIn("badges", data["categories"])

        # Verify hypixel cloak is completely removed
        cloak_ids = [c["id"] for c in data["categories"]["cloaks"]]
        self.assertNotIn("cloak_hypixel_champion", cloak_ids)
        self.assertNotIn("cape_hypixel_champion", cloak_ids)

        # Redeem promo code
        r = self.app.post("/api/ingame/cosmetics/redeem", json={"code": "COSMIC"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["code"], "COSMIC")
        self.assertIn("wings_cosmic_butterfly", r.json["unlocked_items"])

    def test_discord_generated_code_redemption(self):
        # Generate code via API / Bot command
        r = self.app.post("/api/codes/generate", json={
            "item_type": "cloak",
            "item_id": "cloak_solaris_white",
            "title": "Solaris White Cloak",
            "max_uses": 1,
            "creator": "Discord Bot Admin"
        })
        self.assertEqual(r.status_code, 200)
        code_data = r.json["code_data"]
        code = code_data["code"]
        self.assertTrue(code.startswith("DIVINE-"))

        # First redemption succeeds
        r1 = self.app.post("/api/ingame/cosmetics/redeem", json={"code": code, "username": "Player1"})
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json["success"])
        self.assertIn("cloak_solaris_white", r1.json["unlocked_items"])

        # Second redemption fails because max_uses was 1
        r2 = self.app.post("/api/ingame/cosmetics/redeem", json={"code": code, "username": "Player2"})
        self.assertEqual(r2.status_code, 400)
        self.assertFalse(r2.json["success"])
        self.assertIn("already reached maximum uses", r2.json["error"])

    def test_multi_use_generated_code(self):
        # Generate code with 3 uses
        r = self.app.post("/api/codes/generate", json={
            "item_type": "wings",
            "item_id": "wings_angel_pure",
            "title": "Pure Angel Wings",
            "max_uses": 3,
            "creator": "Admin"
        })
        self.assertEqual(r.status_code, 200)
        code = r.json["code_data"]["code"]

        # Use by Player 1
        res1 = self.app.post("/api/ingame/cosmetics/redeem", json={"code": code, "username": "UserA"})
        self.assertEqual(res1.status_code, 200)

        # Same user cannot claim twice
        res1_dup = self.app.post("/api/ingame/cosmetics/redeem", json={"code": code, "username": "UserA"})
        self.assertEqual(res1_dup.status_code, 400)

        # Use by Player 2
        res2 = self.app.post("/api/ingame/cosmetics/redeem", json={"code": code, "username": "UserB"})
        self.assertEqual(res2.status_code, 200)

        # Use by Player 3
        res3 = self.app.post("/api/ingame/cosmetics/redeem", json={"code": code, "username": "UserC"})
        self.assertEqual(res3.status_code, 200)

        # Use by Player 4 should fail
        res4 = self.app.post("/api/ingame/cosmetics/redeem", json={"code": code, "username": "UserD"})
        self.assertEqual(res4.status_code, 400)

    def test_nametag_badge_lookup(self):
        # DivinePlayer must return verified with Divine sun badge (verified players)
        r = self.app.get("/api/ingame/badge-lookup?username=DivinePlayer")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["verified"])
        self.assertEqual(r.json["badge"], "badge_divine_sun_white")
        self.assertEqual(r.json["badge_icon"], "/assets/divine_icon.png")

        # Non-existent user must return not verified
        r = self.app.get("/api/ingame/badge-lookup?username=RandomNonDivineUser999")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json["verified"])

    def test_friends_add_strictly_verifies_divine_account(self):
        # Adding verified user succeeds
        r = self.app.post("/api/social/friends/add", json={"username": "DivinePlayer"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json.get("success"))

        # Adding unregistered non-Divine user fails with 404
        r = self.app.post("/api/social/friends/add", json={"username": "CompletelyUnregisteredPersonXYZ"})
        self.assertEqual(r.status_code, 404)
        self.assertIn("does not have a linked Divine Client account", r.json.get("error", ""))

    def test_rpc_status_and_update(self):
        r = self.app.get("/api/rpc/status")
        self.assertEqual(r.status_code, 200)
        self.assertIn("enabled", r.json)

        r = self.app.post("/api/rpc/update", json={
            "details": "Playing Bedwars",
            "state": "In Game • 4v4v4v4",
            "large_text": "Divine Client v4.0.0"
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["success"])


if __name__ == "__main__":
    unittest.main()
