"""Client and real Tk interactions; GUI cases skip only without a display."""
import importlib.util
import os
import pathlib
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

MODULE = pathlib.Path(__file__).with_name("fileforge_desktop.py")


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), "The desktop client must exist")
        import fileforge_desktop
        self.ui = fileforge_desktop
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = pathlib.Path(self.temp.name)

    def test_client_passes_unicode_folder_and_names_without_a_shell(self):
        folder = self.folder / ("folder café" if os.name == "nt" else 'folder "quoted" café')
        folder.mkdir()
        name = "note café.txt" if os.name == "nt" else "note\nname.txt"
        (folder / name).write_text("hello")
        result = self.ui.EngineClient().run("scan", folder)
        self.assertEqual(result["files"][0]["name"], name)

    def test_client_missing_binary_has_actionable_error(self):
        client = self.ui.EngineClient(self.folder / "missing-engine")
        with self.assertRaisesRegex(self.ui.EngineError, "[Cc]ompile"):
            client.run("scan", self.folder)

    def test_worker_runs_off_thread_and_rejects_double_submission(self):
        worker = self.ui.TaskRunner()
        release = threading.Event()
        self.addCleanup(release.set)
        main_thread = threading.get_ident()
        self.assertTrue(worker.start(lambda: (release.wait(2), threading.get_ident())))
        self.assertFalse(worker.start(lambda: "second operation"))
        self.assertIsNone(worker.poll())
        release.set()
        end = time.monotonic() + 3
        result = None
        while result is None and time.monotonic() < end:
            result = worker.poll()
            time.sleep(0.005)
        self.assertIsNotNone(result)
        self.assertIsNone(result[1])
        self.assertNotEqual(result[0][1], main_thread)
        self.assertFalse(worker.busy)

    def test_worker_error_is_delivered_for_main_thread_handling(self):
        worker = self.ui.TaskRunner()
        worker.start(lambda: self.ui.EngineClient(self.folder / "missing").run("scan", self.folder))
        end = time.monotonic() + 3
        result = None
        while result is None and time.monotonic() < end:
            result = worker.poll()
            time.sleep(0.005)
        self.assertIsInstance(result[1], self.ui.EngineError)
        self.assertFalse(worker.busy)

    def make_app(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk display unavailable; run under Xvfb for GUI coverage")
        self.addCleanup(root.destroy)
        self.app = self.ui.FileForgeApp(root)
        self.root = root
        root.update()
        return self.app

    def wait_idle(self):
        end = time.monotonic() + 5
        while self.app.runner.busy and time.monotonic() < end:
            self.root.update()
            time.sleep(0.01)
        self.root.update()
        self.assertFalse(self.app.runner.busy, "UI operation did not finish")

    def test_first_launch_shows_folder_prompt_instead_of_empty_results(self):
        app = self.make_app()
        self.assertTrue(app.files_empty_panel.winfo_ismapped())
        self.assertFalse(app.files_tree.winfo_ismapped())

    def test_ui_scan_search_sort_preview_cancel_and_roundtrip(self):
        (self.folder / "report.txt").write_text("report")
        (self.folder / "photo.png").write_bytes(b"image")
        (self.folder / "copy.txt").write_text("report")
        app = self.make_app()
        app.load_folder(self.folder)
        self.wait_idle()
        self.assertEqual(len(app.files_tree.get_children()), 3)
        self.assertTrue(app.files_tree.winfo_ismapped())
        self.assertFalse(app.files_empty_panel.winfo_ismapped())
        app.search_var.set("report")
        self.root.update()
        self.assertEqual(len(app.files_tree.get_children()), 1)
        app.search_var.set("")
        app.sort_files("size")
        sizes = [app.files_tree.item(row, "values")[2] for row in app.files_tree.get_children()]
        self.assertEqual(sizes, ["5 B", "6 B", "6 B"])
        app.show_preview()
        self.wait_idle()
        self.assertEqual(len(app.preview_tree.get_children()), 3)
        with patch.object(self.ui.messagebox, "askyesno", return_value=False):
            app.organize_files()
        self.assertTrue((self.folder / "report.txt").exists())
        with patch.object(self.ui.messagebox, "askyesno", return_value=True):
            app.organize_files()
            self.wait_idle()
        self.assertTrue((self.folder / "Documents/report.txt").exists())
        self.assertFalse(app.undo_button.instate(["disabled"]))
        with patch.object(self.ui.messagebox, "askyesno", return_value=True):
            app.undo_files()
            self.wait_idle()
        self.assertTrue((self.folder / "report.txt").exists())
        self.assertEqual(len(app.files_tree.get_children()), 3)

    def test_ui_duplicates_show_groups_and_never_offer_delete(self):
        (self.folder / "a.txt").write_text("same")
        (self.folder / "b.txt").write_text("same")
        app = self.make_app()
        app.load_folder(self.folder)
        self.wait_idle()
        app.find_duplicates()
        self.wait_idle()
        self.assertEqual(len(app.duplicates_tree.get_children()), 1)
        group = app.duplicates_tree.get_children()[0]
        self.assertEqual(len(app.duplicates_tree.get_children(group)), 2)
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    def test_ui_error_recovers_controls_and_empty_filter_explains_result(self):
        (self.folder / "note.txt").write_text("one")
        app = self.make_app()
        app.load_folder(self.folder)
        self.wait_idle()
        app.search_var.set("missing")
        self.root.update()
        self.assertIn("No matches", app.files_empty_var.get())
        app.load_folder(self.folder / "missing")
        self.wait_idle()
        self.assertIn("Folder not found", app.status_var.get())
        self.assertFalse(app.choose_button.instate(["disabled"]))


if __name__ == "__main__":
    unittest.main()
