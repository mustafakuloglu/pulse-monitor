import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from install import bind_command


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'checkout with spaces' / 'monitor.py'
        self.source.parent.mkdir()
        self.source.write_text('#!/usr/bin/env python3\nprint("working")\n')
        self.bin_dir = self.root / 'user bin'

    def test_install_runs_with_spaces_and_is_idempotent(self):
        destination, status = bind_command(self.source, self.bin_dir)
        self.assertEqual(status, 'Installed')
        self.assertTrue(destination.is_symlink())
        result = subprocess.run([str(destination)], capture_output=True, text=True, check=True, timeout=5)
        self.assertEqual(result.stdout.strip(), 'working')
        self.assertEqual(bind_command(self.source, self.bin_dir)[1], 'Already installed')

    def test_existing_file_is_preserved_on_install_and_uninstall(self):
        self.bin_dir.mkdir()
        destination = self.bin_dir / 'monitor'
        destination.write_text('unrelated command')
        for uninstall in (False, True):
            with self.assertRaises(FileExistsError):
                bind_command(self.source, self.bin_dir, uninstall)
            self.assertEqual(destination.read_text(), 'unrelated command')

    def test_unrelated_broken_symlink_is_preserved(self):
        self.bin_dir.mkdir()
        destination = self.bin_dir / 'monitor'
        destination.symlink_to(self.root / 'missing')
        for uninstall in (False, True):
            with self.assertRaises(FileExistsError):
                bind_command(self.source, self.bin_dir, uninstall)
            self.assertEqual(os.readlink(destination), str(self.root / 'missing'))

    def test_uninstall_removes_only_link_and_is_idempotent(self):
        destination, _ = bind_command(self.source, self.bin_dir)
        self.assertEqual(bind_command(self.source, self.bin_dir, True)[1], 'Removed')
        self.assertFalse(os.path.lexists(destination))
        self.assertTrue(self.source.is_file())
        self.assertEqual(bind_command(self.source, self.bin_dir, True)[1], 'Already absent')

    def test_missing_source_does_not_create_command(self):
        with self.assertRaises(FileNotFoundError):
            bind_command(self.root / 'missing.py', self.bin_dir)
        self.assertFalse(self.bin_dir.exists())

    def test_real_installer_cli_and_command(self):
        installer = Path(__file__).resolve().parents[1] / 'install.py'
        result = subprocess.run([sys.executable, str(installer), '--bin-dir', str(self.bin_dir)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(self.bin_dir / 'monitor'), '--help'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--snapshot', result.stdout)
        result = subprocess.run([sys.executable, str(installer), '--bin-dir', str(self.bin_dir), '--uninstall'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.lexists(self.bin_dir / 'monitor'))


if __name__ == '__main__':
    unittest.main()
