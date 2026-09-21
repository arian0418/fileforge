# FileForge

FileForge is a Python desktop application that helps organize cluttered folders, identify duplicate files, preview changes before moving anything, and undo the most recent organization.

## Features

- Choose and scan a folder through a desktop GUI
- View file names, extensions, sizes, and categories
- Organize files into Images, Documents, Videos, Audio, Archives, Code, and Other
- Preview how many files will move into each category
- Detect true duplicate files using SHA-256 hashes
- Avoid overwriting files with duplicate names
- Undo the most recent organization action
- Display basic file and storage statistics
- Unit tests for core file utilities

## Technology

- Python 3
- Tkinter for the desktop interface
- pathlib and shutil for filesystem operations
- hashlib for duplicate detection
- unittest for tests

No third-party packages are required.

## Run

```bash
python fileforge.py
```

Choose a folder containing files, then use the buttons to scan, find duplicates, preview organization, organize, or undo.

## Tests

```bash
python -m unittest
```

## Safety

FileForge does not automatically delete duplicates. Organization requires confirmation, existing filenames are protected from overwriting, and the last organization can be undone.

## What This Project Demonstrates

This project demonstrates Python desktop development, filesystem operations, hashing, data structures, defensive file handling, GUI event handling, and unit testing at a practical undergraduate-project scope.
