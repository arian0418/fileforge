import pathlib
import subprocess
import tempfile
import unittest

BINARY = pathlib.Path(__file__).with_name("fileforge")

def run(folder, commands):
    return subprocess.run([str(BINARY)], input=str(folder) + "\n" + commands,
                          text=True, capture_output=True, check=True)

class FileForgeTests(unittest.TestCase):
    def test_organize_and_undo_files_with_spaces(self):
        with tempfile.TemporaryDirectory() as location:
            folder = pathlib.Path(location)
            (folder / "a report.txt").write_text("one")
            run(folder, "3\ny\n5\n0\n")
            self.assertEqual((folder / "a report.txt").read_text(), "one")
            self.assertFalse((folder / ".fileforge_undo.log").exists())

    def test_undo_rejects_paths_outside_selected_folder(self):
        with tempfile.TemporaryDirectory() as location:
            folder = pathlib.Path(location)
            target = folder / "selected"
            target.mkdir()
            outsider = folder / "outside.txt"
            outsider.write_text("keep")
            (target / ".fileforge_undo.log").write_text(
                f'"{outsider}" "{target / "stolen.txt"}"\\n'.replace("\\\\n", "\\n"))
            run(target, "5\n0\n")
            self.assertEqual(outsider.read_text(), "keep")
            self.assertFalse((target / "stolen.txt").exists())

if __name__ == "__main__":
    unittest.main()
