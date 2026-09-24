"""Behavioral tests for the engine's desktop protocol and file safety."""
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

BINARY = pathlib.Path(__file__).with_name("fileforge.exe" if os.name == "nt" else "fileforge")


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = pathlib.Path(self.temp.name)

    def write(self, name, content=b"sample"):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def command(self, name, *args, ok=True):
        result = subprocess.run(
            [str(BINARY), "--json", name, str(self.folder), *args],
            text=True, encoding="utf-8", capture_output=True,
        )
        self.assertTrue(result.stdout.startswith("{"), "Engine must emit a JSON object")
        data = json.loads(result.stdout)
        self.assertEqual(data["ok"], ok, data)
        self.assertEqual(result.returncode, 0 if ok else 1, data)
        return data

    def organize(self):
        preview = self.command("preview")
        return self.command("organize", "--snapshot", preview["snapshot"])

    def test_scan_excludes_hidden_config_and_app_files(self):
        self.write("report.PDF", b"abc")
        self.write("photo.png", b"12")
        for name in (".env", ".fileforge_undo.tmp", "settings.ini", "package.json",
                     "desktop.ini", "fileforge.exe"):
            self.write(name)
        self.write("nested/leave.txt")
        result = self.command("scan")
        self.assertEqual([f["name"] for f in result["files"]], ["photo.png", "report.PDF"])
        self.assertEqual(result["total_bytes"], 5)
        self.assertEqual(result["skipped_count"], 7)
        self.assertEqual(result["categories"], {"Documents": 1, "Images": 1})

    def test_preview_shows_exact_collision_names_without_changing_files(self):
        self.write("report.txt", b"new")
        self.write("report (1).txt", b"another")
        existing = self.write("Documents/report.txt", b"old")
        result = self.command("preview")
        destinations = {m["source"]: m["destination"] for m in result["moves"]}
        self.assertEqual(destinations, {
            "report (1).txt": "Documents/report (1).txt",
            "report.txt": "Documents/report (2).txt",
        })
        self.assertEqual(existing.read_bytes(), b"old")
        self.assertTrue((self.folder / "report.txt").exists())
        self.assertFalse((self.folder / ".fileforge_undo.log").exists())

    def test_roundtrip_preserves_quotes_unicode_and_newlines(self):
        names = ['a "report".txt', "café 漢字.png", "line\nbreak.txt"]
        if os.name == "nt":
            names = ["a report.txt", "café 漢字.png", "line break.txt"]
        for index, name in enumerate(names):
            self.write(name, str(index).encode())
        self.assertEqual(self.organize()["moved"], 3)
        self.assertTrue(self.command("scan")["undo_available"])
        self.assertEqual(self.command("undo")["restored"], 3)
        for index, name in enumerate(names):
            self.assertEqual((self.folder / name).read_bytes(), str(index).encode())
        self.assertFalse((self.folder / ".fileforge_undo.log").exists())

    def test_stale_preview_aborts_all_moves(self):
        self.write("report.txt", b"new")
        preview = self.command("preview")
        self.write("Documents/report.txt", b"arrived after preview")
        self.command("organize", "--snapshot", preview["snapshot"], ok=False)
        self.assertEqual((self.folder / "report.txt").read_bytes(), b"new")
        self.assertFalse((self.folder / ".fileforge_undo.log").exists())

    def test_organize_requires_preview_snapshot(self):
        self.write("report.txt")
        self.command("organize", ok=False)
        self.assertTrue((self.folder / "report.txt").exists())

    def test_undo_uses_collision_name_and_never_overwrites(self):
        self.write("report.txt", b"organized")
        self.organize()
        self.write("report.txt", b"new arrival")
        self.assertEqual(self.command("undo")["restored"], 1)
        self.assertEqual((self.folder / "report.txt").read_bytes(), b"new arrival")
        self.assertEqual((self.folder / "report (1).txt").read_bytes(), b"organized")

    def test_partial_undo_keeps_missing_entry_for_retry(self):
        self.write("first.txt", b"first")
        self.write("second.txt", b"second")
        self.organize()
        missing = self.folder / "Documents/second.txt"
        held = self.folder / "held"
        missing.rename(held)
        result = self.command("undo")
        self.assertEqual((result["restored"], result["pending_count"]), (1, 1))
        self.assertTrue((self.folder / ".fileforge_undo.log").exists())
        held.rename(missing)
        result = self.command("undo")
        self.assertEqual((result["restored"], result["pending_count"]), (1, 0))
        self.assertEqual((self.folder / "second.txt").read_bytes(), b"second")

    def test_changed_organized_file_stays_pending(self):
        self.write("report.txt", b"original")
        self.organize()
        self.write("Documents/report.txt", b"edited contents")
        result = self.command("undo")
        self.assertEqual((result["restored"], result["pending_count"]), (0, 1))
        self.assertFalse((self.folder / "report.txt").exists())

    def test_second_organization_cannot_replace_recovery_log(self):
        self.write("first.txt")
        self.organize()
        journal = self.folder / ".fileforge_undo.log"
        before = journal.read_bytes()
        self.write("second.txt")
        preview = self.command("preview")
        self.command("organize", "--snapshot", preview["snapshot"], ok=False)
        self.assertEqual(journal.read_bytes(), before)
        self.assertTrue((self.folder / "second.txt").exists())

    def test_duplicates_are_exact_groups_and_report_only(self):
        self.write("first.bin", b"abcd")
        self.write("copy.bin", b"abcd")
        self.write("different.bin", b"wxyz")
        self.write("empty.txt", b"")
        self.write("empty-copy.txt", b"")
        result = self.command("duplicates")
        groups = {tuple(sorted(group["files"])) for group in result["groups"]}
        self.assertEqual(groups, {("copy.bin", "first.bin"), ("empty-copy.txt", "empty.txt")})
        self.assertEqual(result["duplicate_count"], 2)
        self.assertEqual(result["reclaimable_bytes"], 4)
        self.assertEqual(len(list(self.folder.iterdir())), 5)

    @unittest.skipUnless(hasattr(pathlib.Path, "symlink_to"), "Requires symlinks")
    @unittest.skipIf(os.name == "nt", "Symlink permissions vary on Windows; covered on Linux")
    def test_symlink_files_are_not_scanned(self):
        self.write("real.txt")
        (self.folder / "link.txt").symlink_to(self.folder / "real.txt")
        (self.folder / "dangling.txt").symlink_to(self.folder / "absent.txt")
        self.assertEqual([f["name"] for f in self.command("scan")["files"]], ["real.txt"])

    @unittest.skipIf(os.name == "nt", "Symlink permissions vary on Windows; covered on Linux")
    def test_category_symlink_blocks_moves_outside_selected_folder(self):
        self.write("report.txt")
        with tempfile.TemporaryDirectory() as outside:
            (self.folder / "Documents").symlink_to(outside, target_is_directory=True)
            preview = self.command("preview")
            self.assertTrue(preview["blockers"])
            self.command("organize", "--snapshot", preview["snapshot"], ok=False)
            self.assertEqual(list(pathlib.Path(outside).iterdir()), [])
            self.assertTrue((self.folder / "report.txt").exists())

    @unittest.skipIf(os.name == "nt", "Symlink permissions vary on Windows; covered on Linux")
    def test_undo_log_symlink_is_not_read_or_written(self):
        self.write("report.txt")
        with tempfile.TemporaryDirectory() as outside:
            target = pathlib.Path(outside) / "keep.log"
            target.write_text("keep")
            (self.folder / ".fileforge_undo.log").symlink_to(target)
            preview = self.command("preview")
            self.command("organize", "--snapshot", preview["snapshot"], ok=False)
            self.command("undo", ok=False)
            self.assertEqual(target.read_text(), "keep")

    def test_undo_rejects_malformed_or_outside_log(self):
        self.write("Documents/report.txt", b"keep")
        journal = self.write(".fileforge_undo.log", b'"../outside.txt" "stolen.txt"\n')
        self.command("undo", ok=False)
        self.assertEqual((self.folder / "Documents/report.txt").read_bytes(), b"keep")
        self.assertTrue(journal.exists())

    @unittest.skipIf(os.name == "nt", "Symlink permissions vary on Windows; covered on Linux")
    def test_undo_rejects_category_directory_replaced_by_symlink(self):
        self.write("report.txt")
        self.organize()
        (self.folder / "Documents").rename(self.folder / "original-documents")
        with tempfile.TemporaryDirectory() as outside:
            foreign = pathlib.Path(outside) / "report.txt"
            foreign.write_text("foreign")
            (self.folder / "Documents").symlink_to(outside, target_is_directory=True)
            self.command("undo", ok=False)
            self.assertEqual(foreign.read_text(), "foreign")
            self.assertFalse((self.folder / "report.txt").exists())

    @unittest.skipUnless(os.name == "nt", "Windows file attributes")
    def test_windows_hidden_and_system_files_are_excluded(self):
        import ctypes
        self.write("visible.txt")
        for name, flag in [("hidden.txt", 2), ("system.txt", 4)]:
            path = self.write(name)
            self.assertTrue(ctypes.windll.kernel32.SetFileAttributesW(str(path), flag))
        result = self.command("scan")
        self.assertEqual([item["name"] for item in result["files"]], ["visible.txt"])

    def test_missing_folder_returns_machine_readable_error(self):
        self.folder = self.folder / "not-here"
        result = self.command("scan", ok=False)
        self.assertTrue(result["error"])


if __name__ == "__main__":
    unittest.main()
