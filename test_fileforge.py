import tempfile
import unittest
from pathlib import Path
from fileforge import category_for, file_hash, format_size

class FileForgeTests(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(category_for(Path("photo.jpg")), "Images")
        self.assertEqual(category_for(Path("notes.pdf")), "Documents")
        self.assertEqual(category_for(Path("unknown.xyz")), "Other")

    def test_size_format(self):
        self.assertEqual(format_size(500), "500.0 B")
        self.assertEqual(format_size(2048), "2.0 KB")

    def test_hash_detects_equal_content(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "a.txt"
            second = Path(folder) / "b.txt"
            first.write_text("same content")
            second.write_text("same content")
            self.assertEqual(file_hash(first), file_hash(second))

if __name__ == "__main__":
    unittest.main()
