"""Tests for Mod Library Duplicate Prevention and Ultimate Optimization Suite."""
import os
import shutil
import sys
import tempfile
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from divineclient.core import mods, modrinth
from divineclient.core.instances import InstanceManager


def test_mod_stem_normalization():
    assert modrinth._mod_stem("sodium-fabric-mc1.21.4-0.6.0.jar") == "sodium"
    assert modrinth._mod_stem("lithium-fabric-0.15.3.jar") == "lithium"
    assert modrinth._mod_stem("iris-mc1.21.4-1.8.0.jar") == "iris"
    assert modrinth._mod_stem("cull-less-leaves-1.20.1-2.2.2.jar") == "cull-less-leaves"
    assert modrinth._mod_stem("fabric-api-0.119.4+1.21.4.jar") == "fabric-api"


def test_clean_duplicate_jars():
    tmp = tempfile.mkdtemp(prefix="divine-dup-mods-")
    try:
        # Create an older sodium jar
        old_sodium = os.path.join(tmp, "sodium-fabric-0.5.8.jar")
        with open(old_sodium, "w") as f:
            f.write("old_sodium_data")

        # Create another mod that shouldn't be touched
        other_mod = os.path.join(tmp, "lithium-0.15.0.jar")
        with open(other_mod, "w") as f:
            f.write("lithium_data")

        assert os.path.exists(old_sodium)
        assert os.path.exists(other_mod)

        # Download or install new sodium jar -> cleans old sodium
        removed = modrinth._clean_duplicate_jars(tmp, "sodium", exclude_filename="sodium-fabric-0.6.0.jar")
        assert "sodium-fabric-0.5.8.jar" in removed
        assert not os.path.exists(old_sodium)
        assert os.path.exists(other_mod)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ultimate_optimization_pack_definition():
    assert len(mods.ULTIMATE_OPTIMIZATION_PACK) >= 12
    slugs = [s for s, _ in mods.ULTIMATE_OPTIMIZATION_PACK]
    assert "fabric-api" in slugs
    assert "sodium" in slugs
    assert "iris" in slugs
    assert "lithium" in slugs
    assert "ferrite-core" in slugs
    assert "entityculling" in slugs
    assert "immediatelyfast" in slugs
    assert "modernfix" in slugs
    assert "memoryleakfix" in slugs


def test_best_version_for_project_sorting():
    fake_versions = [
        {
            "id": "v1-alpha",
            "version_number": "1.0.0-alpha.1",
            "version_type": "alpha",
            "date_published": "2026-05-01T00:00:00Z",
            "game_versions": ["1.21.4"],
            "files": [{"filename": "mod-1.0.0-alpha.1.jar", "url": "http://example.com/1", "primary": True}]
        },
        {
            "id": "v2-release",
            "version_number": "0.9.5",
            "version_type": "release",
            "date_published": "2026-04-01T00:00:00Z",
            "game_versions": ["1.21.4"],
            "files": [{"filename": "mod-0.9.5.jar", "url": "http://example.com/2", "primary": True}]
        },
    ]

    # Mock get_versions
    orig = modrinth.get_versions
    try:
        modrinth.get_versions = lambda proj, mc, loader: fake_versions
        best = modrinth._best_version_for_project("test-mod", "1.21.4", "fabric")
        assert best is not None
        # Must prefer release over alpha
        assert best["id"] == "v2-release"
        assert best["version_type"] == "release"
    finally:
        modrinth.get_versions = orig

def test_validate_and_fix_instance_mods_api():
    from divineclient import web_server
    from divineclient.core.instances import InstanceManager
    from divineclient.core.config import Config
    import divineclient.paths as paths

    td = tempfile.mkdtemp()
    try:
        gamedir = os.path.join(td, 'game')
        os.makedirs(gamedir, exist_ok=True)
        orig_gamedir = paths.get_game_dir()
        paths.set_game_dir(gamedir)

        cfg = Config()
        cfg.save()
        inst_mgr = InstanceManager()
        web_server.cfg_store = cfg
        web_server.inst_mgr = inst_mgr
        web_server.app.config['TESTING'] = True
        client = web_server.app.test_client()

        # Create an instance
        res = client.post('/api/instances', json={
            'name': 'Test Opt Instance',
            'mc_version': '1.21.4',
            'loader': 'fabric',
            'ram_mb': 4096,
            'install_optimization_pack': False
        })
        data = res.get_json()
        assert data['success'] is True
        inst_id = data['instance']['id']

        # Call validate-and-fix endpoint
        val_res = client.post(f'/api/instances/{inst_id}/mods/validate-and-fix', json={'auto_fix': False})
        val_data = val_res.get_json()
        assert val_data['success'] is True
        assert 'missing_dependencies' in val_data
        assert 'cleaned_duplicates' in val_data

        # Test auto_fix=True
        fix_res = client.post(f'/api/instances/{inst_id}/mods/validate-and-fix', json={'auto_fix': True})
        fix_data = fix_res.get_json()
        assert fix_data['success'] is True
        assert 'removed_duplicates' in fix_data
        assert 'installed_dependencies' in fix_data

        paths.set_game_dir(orig_gamedir)
    finally:
        shutil.rmtree(td, ignore_errors=True)
