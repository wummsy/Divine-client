"""Tests for Divine Client Installer & Setup Engine."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from installer import (
    fetch_latest_release_info,
    compute_file_sha256,
    safe_extract_zip,
    create_linux_desktop_file,
    InstallerEngine,
    run_cli_installer,
    format_bytes,
)


def test_format_bytes():
    assert format_bytes(500) == "500 B"
    assert "KB" in format_bytes(2048)
    assert "MB" in format_bytes(5 * 1024 * 1024)
    assert "GB" in format_bytes(3 * 1024 * 1024 * 1024)


def test_compute_file_sha256():
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(b"Divine Client Installer Test Payload")
        tf_path = tf.name

    try:
        digest = compute_file_sha256(tf_path)
        expected = hashlib.sha256(b"Divine Client Installer Test Payload").hexdigest()
        assert digest == expected
    finally:
        if os.path.exists(tf_path):
            os.remove(tf_path)


def test_safe_extract_zip_prevents_traversal():
    tmp_dir = tempfile.mkdtemp(prefix="divine-inst-test-")
    zip_path = os.path.join(tmp_dir, "test.zip")
    extract_dir = os.path.join(tmp_dir, "extracted")

    try:
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("aren-client/main.py", "print('hello from main')")
            zf.writestr("aren-client/assets/logo.png", "fake_png_data")
            # attempt malicious traversal entry
            zf.writestr("aren-client/../../outside.txt", "should not be extracted outside")

        safe_extract_zip(zip_path, extract_dir)

        # check that wrapper folder was stripped and valid files exist
        assert os.path.isfile(os.path.join(extract_dir, "main.py"))
        assert os.path.isfile(os.path.join(extract_dir, "assets", "logo.png"))
        assert not os.path.exists(os.path.join(tmp_dir, "outside.txt"))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_installer_engine_mock_install():
    tmp_dir = tempfile.mkdtemp(prefix="divine-engine-test-")
    mock_zip = os.path.join(tmp_dir, "DivineClient-v2.0.zip")
    install_target = os.path.join(tmp_dir, "InstallTarget")

    try:
        with zipfile.ZipFile(mock_zip, "w") as zf:
            zf.writestr("DivineClient.exe", "fake_exe_content")
            zf.writestr("assets/emblem.png", "fake_emblem")

        sha = compute_file_sha256(mock_zip)
        rel_info = {
            "version": "2.0.0",
            "url": "",  # local fallback
            "sha256": sha,
            "size": os.path.getsize(mock_zip),
            "file": "DivineClient-v2.0.zip",
        }

        engine = InstallerEngine(target_dir=install_target, release_info=rel_info)
        engine.downloaded_archive = mock_zip

        installed_exe = engine.install(create_desktop=False, create_startmenu=False)
        assert os.path.isfile(installed_exe)
        assert os.path.basename(installed_exe) == "DivineClient.exe"
        assert os.path.isfile(os.path.join(install_target, "assets", "emblem.png"))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_cli_installer_check_only(capsys):
    ret = run_cli_installer(["--check-only"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Latest Version" in captured.out


def test_updater_module_intact():
    """Verify that auto-updater in arenclient.core.updater is present and unaffected."""
    from arenclient.core import updater
    assert hasattr(updater, "fetch_latest")
    assert hasattr(updater, "download")
    assert hasattr(updater, "apply_later")
    assert hasattr(updater, "apply_update_from_zip")
    assert hasattr(updater, "status")
