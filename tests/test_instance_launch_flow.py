"""Tests for Divine Client instance launching and command generation."""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from divineclient import paths
from divineclient.core import instances, launcher, accounts, config


class TestInstanceLaunchFlow(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="divine_test_launch_")
        self.orig_data_dir = paths.DATA_DIR
        self.orig_mc_dir = paths.MINECRAFT_DIR
        self.orig_inst_dir = paths.INSTANCES_DIR

        paths.DATA_DIR = os.path.join(self.tmp_dir, "data")
        paths.MINECRAFT_DIR = os.path.join(self.tmp_dir, "minecraft")
        paths.INSTANCES_DIR = os.path.join(self.tmp_dir, "instances")
        paths.LOG_DIR = os.path.join(self.tmp_dir, "logs")
        paths.ensure_dirs()

        paths.CONFIG_FILE = os.path.join(self.tmp_dir, "config.json")
        self.cfg = config.Config()
        paths.ACCOUNTS_FILE = os.path.join(self.tmp_dir, "accounts.json")
        self.accs = accounts.AccountStore()
        self.accs.add_offline("DivinePlayer")

        self.inst_mgr = instances.InstanceManager()

    def tearDown(self):
        paths.DATA_DIR = self.orig_data_dir
        paths.MINECRAFT_DIR = self.orig_mc_dir
        paths.INSTANCES_DIR = self.orig_inst_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_and_resolve_multiple_instances(self):
        """Verify creating multiple distinct instances and verifying each targets its own folder and version."""
        inst1 = self.inst_mgr.create("PvP Modern", "1.21.4", loader="fabric")
        inst2 = self.inst_mgr.create("Survival Classic", "1.20.1", loader="forge")
        inst3 = self.inst_mgr.create("Pure Vanilla", "1.16.5", loader="vanilla")

        self.assertEqual(len(self.inst_mgr.instances), 3)
        self.assertEqual(self.inst_mgr.get(inst1.id).mc_version, "1.21.4")
        self.assertEqual(self.inst_mgr.get(inst2.id).loader, "forge")
        self.assertEqual(self.inst_mgr.get(inst3.id).mc_version, "1.16.5")

        # Verify isolated game directories
        self.assertNotEqual(inst1.game_dir, inst2.game_dir)
        self.assertTrue(os.path.isdir(inst1.game_dir))
        self.assertTrue(os.path.isdir(inst2.game_dir))

    @patch("minecraft_launcher_lib.install.install_minecraft_version")
    @patch("minecraft_launcher_lib.command.get_minecraft_command")
    @patch("divineclient.core.java_runtime.ensure_java")
    def test_launch_command_generation_for_specific_instance(self, mock_java, mock_cmd, mock_install):
        """Verify building launch command targets the exact instance and directory."""
        mock_java.return_value = "/usr/bin/java"
        mock_cmd.return_value = ["/usr/bin/java", "-Xmx4096M", "net.minecraft.client.main.Main"]

        inst = self.inst_mgr.create("Speedrun Setup", "1.21.4", loader="vanilla")
        prog = launcher.Progress()

        cmd = launcher.build_command(inst, self.cfg, self.accs, prog)
        self.assertTrue(cmd)
        self.assertEqual(cmd[0], "/usr/bin/java")

        # Check that get_minecraft_command was invoked with the instance's gameDirectory and options
        mock_cmd.assert_called_once()
        args, kwargs = mock_cmd.call_args
        options = args[2]
        self.assertEqual(options["gameDirectory"], inst.game_dir)
        self.assertEqual(options["username"], "DivinePlayer")
        self.assertEqual(options["launcherName"], "DivineClient")
        self.assertEqual(options["launcherVersion"], "5.0.0")


if __name__ == "__main__":
    unittest.main()
