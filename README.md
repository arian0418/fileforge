# FileForge — C++ File Organizer

FileForge is a command-line file organization utility built primarily in **C++17**. It scans a folder, categorizes files, previews where they will go, organizes them into folders, identifies duplicate candidates, and can undo the most recent organization.

## Why I Built This

My computer was getting cluttered with downloads, duplicate files, old documents, and files spread across different folders. I wanted a simple way to see what was taking up space and organize everything without manually sorting through files one by one.

I built FileForge to solve that problem for myself. It lets me scan a folder, understand how the files are organized, find possible duplicates, safely sort files by type, and undo the most recent organization if needed. Building it also gave me a practical way to learn more about C++ file handling and `std::filesystem`.

## Main language
**C++**

It uses the C++17 standard library, especially `std::filesystem`, containers, streams, and file I/O. No Python packages or external dependencies are required.

## Features
- Scan top-level files and show sizes/categories
- Preview organization before changing files
- Organize into Images, Documents, Videos, Audio, Archives, Code, and Other
- Collision-safe file naming
- Duplicate-candidate detection by file size
- Undo the most recent organization using a local log; incomplete restores keep pending entries for retry
- Reject undo records that point outside the selected folder and skip symlinks
- Refuse a new organization while an undo record exists
- Storage summary

Duplicate detection intentionally reports **candidates** when sizes match; it does not claim the files are byte-for-byte identical.

## Compile

### Windows with g++
```
g++ -std=c++17 -O2 fileforge.cpp -o fileforge.exe
fileforge.exe
```

### Linux/macOS
```
g++ -std=c++17 -O2 fileforge.cpp -o fileforge
./fileforge
```

FileForge demonstrates practical use of C++ filesystem APIs, STL containers, path handling, error handling, and safe file operations.

## Tests

Compile using the command above, then run `python -m unittest discover -v` (Python 3). GitHub Actions compiles and runs these tests on each pull request.

The undo log is stored in the selected folder. Keep it until you have restored the files you need; FileForge refuses to start a new organization while an undo record exists.
