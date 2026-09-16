"""Tests for the Server Management Suite, File Manager, Whitelist/Ops, and Static IP."""
import json
import os
import shutil
import sys
import tempfile
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from arenclient import paths
from arenclient.core.config import Config
from arenclient.core.instances import InstanceManager
from arenclient import web_server


@pytest.fixture
def test_env():
    td = tempfile.mkdtemp()
    gamedir = os.path.join(td, "game")
    os.makedirs(gamedir, exist_ok=True)
    orig_gamedir = paths.get_game_dir()
    paths.set_game_dir(gamedir)

    cfg = Config()
    cfg.set("servers_unlocked", True)
    cfg.set("redeemed_codes", [])
    cfg.set("max_servers_limit", 1)
    cfg.save()

    inst_mgr = InstanceManager()
    inst = inst_mgr.create("Test Dedicated Server", "1.21.1", "paper", extra={"is_server": True, "static_domain": "play.testmc.com"})

    # Create dummy server directory files
    sdir = os.path.join(gamedir, "servers", inst.id)
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "server.properties"), "w") as f:
        f.write("motd=Divine Server Test\nserver-port=25565\nmax-players=20\n")

    web_server.cfg_store = cfg
    web_server.inst_mgr = inst_mgr
    web_server.app.config["TESTING"] = True
    client = web_server.app.test_client()

    yield {
        "client": client,
        "inst": inst,
        "sdir": sdir,
        "inst_mgr": inst_mgr,
        "cfg": cfg,
    }

    paths.set_game_dir(orig_gamedir)
    shutil.rmtree(td, ignore_errors=True)


def test_list_server_instances_returns_cards_data(test_env):
    client = test_env["client"]
    inst = test_env["inst"]

    res = client.get("/api/servers/instances")
    assert res.status_code == 200
    data = res.get_json()
    assert "servers" in data
    assert len(data["servers"]) >= 1

    srv = next(s for s in data["servers"] if s["instance_id"] == inst.id)
    assert srv["name"] == "Test Dedicated Server"
    assert srv["loader"] == "paper"
    assert srv["status"] == "stopped"
    assert srv["public_address"] == "play.testmc.com"
    assert srv["static_domain"] == "play.testmc.com"
    assert "storage_mb" in srv
    assert "cpu_percent" in srv


def test_server_file_manager_crud(test_env):
    client = test_env["client"]
    inst = test_env["inst"]
    sdir = test_env["sdir"]

    # 1. List files
    res = client.get(f"/api/servers/{inst.id}/files")
    assert res.status_code == 200
    files = res.get_json()["files"]
    assert any(f["name"] == "server.properties" for f in files)

    # 2. Read file
    res = client.get(f"/api/servers/{inst.id}/files/read?file=server.properties")
    assert res.status_code == 200
    assert "Divine Server Test" in res.get_json()["content"]

    # 3. Write file
    new_content = "motd=Updated MOTD\nserver-port=25565\n"
    res = client.post(f"/api/servers/{inst.id}/files/write", json={
        "file": "server.properties",
        "content": new_content,
    })
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # Verify write
    with open(os.path.join(sdir, "server.properties"), "r") as f:
        assert f.read() == new_content

    # 4. Create & Delete file
    res = client.post(f"/api/servers/{inst.id}/files/write", json={
        "file": "test-to-delete.txt",
        "content": "bye",
    })
    assert res.status_code == 200
    assert os.path.isfile(os.path.join(sdir, "test-to-delete.txt"))

    # 5. Create folder
    res = client.post(f"/api/servers/{inst.id}/files/create-folder", json={
        "folder": "plugins/Essentials"
    })
    assert res.status_code == 200
    assert os.path.isdir(os.path.join(sdir, "plugins", "Essentials"))

    # 6. Rename file
    res = client.post(f"/api/servers/{inst.id}/files/rename", json={
        "old_path": "test-to-delete.txt",
        "new_path": "renamed-test.txt"
    })
    assert res.status_code == 200
    assert os.path.isfile(os.path.join(sdir, "renamed-test.txt"))

    # 7. Upload file via base64
    res = client.post(f"/api/servers/{inst.id}/files/upload", json={
        "filename": "uploaded-test.txt",
        "content": "hello from upload"
    })
    assert res.status_code == 200
    assert os.path.isfile(os.path.join(sdir, "uploaded-test.txt"))

    # 8. Download file
    res = client.get(f"/api/servers/{inst.id}/files/download?file=uploaded-test.txt")
    assert res.status_code == 200
    assert b"hello from upload" in res.data

    # 9. Delete file
    res = client.post(f"/api/servers/{inst.id}/files/delete", json={
        "file": "renamed-test.txt",
    })
    assert res.status_code == 200
    assert not os.path.exists(os.path.join(sdir, "renamed-test.txt"))


def test_create_server_and_quota_limit(test_env):
    client = test_env["client"]
    cfg = test_env["cfg"]
    cfg.set("max_servers_limit", 1)
    cfg.save()

    # We already have 1 server created in test_env setup.
    # Trying to create a 2nd server should be blocked by 1-server limit:
    res = client.post("/api/servers/create", json={
        "name": "Second Dedicated Server",
        "mc_version": "1.21.4",
        "loader": "paper",
    })
    assert res.status_code == 400
    assert res.get_json().get("quota_reached") is True

    # Redeem a code to unlock another slot:
    res = client.post("/api/servers/redeem", json={"code": "AREV-SLOT-TEST-CODE"})
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # Now creating the 2nd server succeeds:
    res = client.post("/api/servers/create", json={
        "name": "Second Dedicated Server",
        "mc_version": "1.21.4",
        "loader": "paper",
    })
    assert res.status_code == 200
    assert res.get_json()["success"] is True


def test_import_instance_to_server(test_env):
    client = test_env["client"]
    inst_mgr = test_env["inst_mgr"]
    cfg = test_env["cfg"]
    cfg.set("max_servers_limit", 5)
    cfg.save()

    # Create a client instance with dummy world save
    client_inst = inst_mgr.create("My Solo World", "1.21.1", "fabric")
    saves_dir = os.path.join(client_inst.game_dir, "saves", "New World")
    os.makedirs(saves_dir, exist_ok=True)
    with open(os.path.join(saves_dir, "level.dat"), "w") as f:
        f.write("dummy-world-data")

    # Import instance to server
    res = client.post("/api/servers/import-instance", json={
        "source_instance_id": client_inst.id,
        "name": "Imported Solo World Server",
        "ram_mb": 4096,
        "server_port": 25565,
    })
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # Verify world was imported into dedicated server directory
    new_inst_id = res.get_json()["instance"]["id"]
    srv = web_server.server_mgr.get(new_inst_id)
    assert srv is not None
    sdir = srv.server_dir
    assert os.path.isfile(os.path.join(sdir, "world", "level.dat"))


def test_server_network_and_playit_settings(test_env):
    client = test_env["client"]
    inst = test_env["inst"]

    # Save network settings with playit secret
    res = client.post(f"/api/servers/{inst.id}/network", json={
        "tunnel_provider": "playit",
        "static_domain": "myserver.craft.playit.gg",
        "playit_secret": "sec_test_playit_token_12345",
        "bore_static_port": ""
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True

    # Retrieve network settings
    res = client.get(f"/api/servers/{inst.id}/network")
    assert res.status_code == 200
    net = res.get_json()
    assert net["tunnel_provider"] == "playit"
    assert net["static_domain"] == "myserver.craft.playit.gg"
    assert net["playit_secret"] == "sec_test_playit_token_12345"

    # Verify server detail info returns the static domain as public address
    res = client.get(f"/api/servers/{inst.id}/info")
    assert res.status_code == 200
    info = res.get_json()
    assert info["public_address"] == "myserver.craft.playit.gg"
    assert info["playit_secret"] == "sec_test_playit_token_12345"


def test_user_redeemed_codes_endpoint(test_env):
    client = test_env["client"]
    res = client.get("/api/user/redeemed-codes")
    assert res.status_code == 200
    data = res.get_json()
    assert "codes" in data
    assert "max_servers_limit" in data

def test_server_sub_user_access(test_env):
    client = test_env["client"]
    inst = test_env["inst"]

    # 1. Initially empty access list
    res = client.get(f"/api/servers/{inst.id}/access")
    assert res.status_code == 200
    assert "users" in res.get_json()

    # 2. Add a collaborator / sub-user
    res = client.post(f"/api/servers/{inst.id}/access/add", json={
        "username": "alex_crafter",
        "permissions": ["power", "console", "files"]
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert any(u["username"] == "alex_crafter" for u in data["users"])

    # 3. Verify access list has the user
    res = client.get(f"/api/servers/{inst.id}/access")
    assert res.status_code == 200
    assert any(u["username"] == "alex_crafter" for u in res.get_json()["users"])

    # 4. Revoke access
    res = client.post(f"/api/servers/{inst.id}/access/remove", json={
        "username": "alex_crafter"
    })
    assert res.status_code == 200
    assert not any(u["username"] == "alex_crafter" for u in res.get_json()["users"])

def test_friend_management_routes(test_env, monkeypatch):
    client = test_env["client"]
    from arenclient.core import social

    # Mock social actions to simulate connected user responses
    monkeypatch.setattr(social, "add_friend", lambda cfg, u: {"success": True, "target": u})
    monkeypatch.setattr(social, "accept_friend", lambda cfg, uid: {"success": True, "accepted": uid})
    monkeypatch.setattr(social, "remove_friend", lambda cfg, uid: {"success": True, "removed": uid})

    # 1. Add friend
    res = client.post("/api/social/friends/add", json={"username": "SteveMinecraft"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True

    # 2. Accept friend
    res = client.post("/api/social/friends/accept", json={"user_id": "SteveMinecraft"})
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # 3. Remove friend
    res = client.post("/api/social/friends/remove", json={"user_id": "SteveMinecraft"})
    assert res.status_code == 200
    assert res.get_json()["success"] is True

def test_clear_servers_data_endpoint(test_env):
    client = test_env["client"]
    inst = test_env["inst"]

    # 1. Clear server data
    res = client.post("/api/servers/clear-data")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True

    # 2. Check servers list is now empty of dedicated servers
    res = client.get("/api/servers/instances")
    assert res.status_code == 200
    assert len(res.get_json()["servers"]) == 0


def test_redeem_code_verification_online_and_offline(test_env, monkeypatch):
    client = test_env["client"]
    from arenclient.core import endpoints

    # 1. Test empty code error
    res = client.post("/api/servers/redeem", json={"code": ""})
    assert res.status_code == 400
    assert "required" in res.get_json()["error"].lower()

    # 2. Test successful redemption of a +3 slot code with mock online server
    monkeypatch.setattr(
        endpoints,
        "post_json",
        lambda cfg, path, data, timeout=4: ({"success": True, "product_id": "server_slots_3", "message": "Claimed 3 slots!"}, 200, True)
    )
    res = client.post("/api/servers/redeem", json={"code": "AREV-3SLOTS-BONUS"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["new_limit"] == 4  # 1 initial + 3 = 4
    assert data["product_id"] == "server_slots_3"

    # 3. Test duplicate code error
    res = client.post("/api/servers/redeem", json={"code": "AREV-3SLOTS-BONUS"})
    assert res.status_code == 400
    assert "already been redeemed" in res.get_json()["error"]

    # 4. Test static IP redemption
    monkeypatch.setattr(
        endpoints,
        "post_json",
        lambda cfg, path, data, timeout=4: ({"success": True, "product_id": "static_ip", "message": "Static IP active!"}, 200, True)
    )
    res = client.post("/api/servers/redeem", json={"code": "AREV-STATIC-IP-PRO"})
    assert res.status_code == 200
    assert res.get_json()["product_id"] == "static_ip"

    # 5. Test invalid code returned by server
    monkeypatch.setattr(
        endpoints,
        "post_json",
        lambda cfg, path, data, timeout=4: ({"error": "Invalid or expired redemption code."}, 400, False)
    )
    res = client.post("/api/servers/redeem", json={"code": "AREV-INVALID-EXPIRED"})
    assert res.status_code == 400
    assert "Invalid or expired" in res.get_json()["error"]


def test_delete_dedicated_server_removes_files_and_does_not_resurrect(test_env):
    client = test_env["client"]
    inst = test_env["inst"]
    sdir = test_env["sdir"]

    # Verify server exists in instances list
    res = client.get("/api/servers/instances")
    assert res.status_code == 200
    servers = res.get_json()["servers"]
    assert any(s["instance_id"] == inst.id for s in servers)
    assert os.path.exists(sdir)

    # Delete the dedicated server
    res = client.post(f"/api/servers/{inst.id}/delete")
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # Verify server directory is deleted
    assert not os.path.exists(sdir)

    # Verify server is no longer in list of servers
    res = client.get("/api/servers/instances")
    assert res.status_code == 200
    servers = res.get_json()["servers"]
    assert not any(s["instance_id"] == inst.id for s in servers)

    # Verify reload does not auto-resurrect phantom server
    web_server.server_mgr.load()
    assert web_server.server_mgr.get(inst.id) is None


def test_server_plugin_store_and_install(test_env, monkeypatch):
    client = test_env["client"]
    inst = test_env["inst"]
    sdir = test_env["sdir"]
    from arenclient.core import modrinth

    # Mock modrinth search and versions
    monkeypatch.setattr(modrinth, "search", lambda query, mc_version=None, loader="paper", category=None, project_type="plugin", limit=24, offset=0: (
        [{"project_id": "test-plugin-id", "slug": "test-plugin", "title": "Test Plugin", "downloads": 5000, "description": "A cool plugin", "author": "Tester"}],
        1
    ))
    monkeypatch.setattr(modrinth, "get_versions", lambda slug_or_id, mc_version=None, loader="paper": [
        {"id": "v1", "filename": "TestPlugin-1.0.jar", "url": "https://example.com/TestPlugin-1.0.jar", "size": 1024}
    ])

    # 1. Search plugins
    res = client.get("/api/plugins/search?q=test")
    assert res.status_code == 200
    hits = res.get_json()["hits"]
    assert len(hits) == 1
    assert hits[0]["title"] == "Test Plugin"

    # 2. Mock urllib download and test plugin installation
    import urllib.request
    class DummyResp:
        def read(self):
            return b"fake-plugin-jar-bytes"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=25: DummyResp())

    res = client.post(f"/api/servers/{inst.id}/plugins/install", json={"project_id": "test-plugin-id"})
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # 3. Check file is installed in server plugins dir
    pdir = os.path.join(sdir, "plugins")
    assert os.path.isfile(os.path.join(pdir, "TestPlugin-1.0.jar"))

    # 4. List plugins
    res = client.get(f"/api/servers/{inst.id}/plugins")
    assert res.status_code == 200
    plugins = res.get_json()["plugins"]
    assert any(p["filename"] == "TestPlugin-1.0.jar" for p in plugins)

    # 5. Delete plugin
    res = client.post(f"/api/servers/{inst.id}/plugins/delete", json={"filename": "TestPlugin-1.0.jar"})
    assert res.status_code == 200
    assert not os.path.exists(os.path.join(pdir, "TestPlugin-1.0.jar"))




