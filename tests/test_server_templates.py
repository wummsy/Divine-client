import unittest
from divineclient.core import server_host
from divineclient import web_server


class TestServerTemplatesSystem(unittest.TestCase):
    def setUp(self):
        self.app = web_server.app.test_client()

    def test_get_server_templates(self):
        templates = server_host.get_server_templates()
        self.assertGreaterEqual(len(templates), 5)
        ids = [t["id"] for t in templates]
        self.assertIn("survival", ids)
        self.assertIn("creative", ids)
        self.assertIn("lobby", ids)
        self.assertIn("hardcore", ids)
        self.assertIn("fabric", ids)
        self.assertIn("custom", ids)

    def test_get_server_template_properties(self):
        survival = server_host.get_server_template("survival")
        self.assertEqual(survival["loader"], "paper")
        self.assertEqual(survival["properties"]["motd"], "created by Divine client servers")
        self.assertEqual(survival["properties"]["gamemode"], "survival")

        creative = server_host.get_server_template("creative")
        self.assertEqual(creative["properties"]["gamemode"], "creative")
        self.assertEqual(creative["properties"]["allow-flight"], "true")

    def test_register_server_template(self):
        new_template = {
            "id": "anarchy",
            "name": "Anarchy Realm (No Rules)",
            "category": "PvP",
            "loader": "paper",
            "mc_version": "1.21.4",
            "ram_mb": 8192,
            "properties": {
                "gamemode": "survival",
                "difficulty": "hard",
                "pvp": "true",
                "motd": "created by Divine client servers"
            }
        }
        res = server_host.register_server_template(new_template)
        self.assertTrue(res)
        retrieved = server_host.get_server_template("anarchy")
        self.assertEqual(retrieved["name"], "Anarchy Realm (No Rules)")

    def test_server_templates_api_endpoints(self):
        r = self.app.get("/api/servers/templates")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["success"])
        self.assertGreaterEqual(len(r.json["templates"]), 5)

        # Dynamic template registration via API
        r2 = self.app.post("/api/servers/templates/register", json={
            "id": "bedwars_hub",
            "name": "Bedwars Minigames Hub",
            "category": "Minigames",
            "loader": "paper",
            "ram_mb": 4096
        })
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json["success"])


if __name__ == "__main__":
    unittest.main()
