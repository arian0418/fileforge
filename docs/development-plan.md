# FileForge development plan

Keep the C++17 file engine and its interactive CLI. Add a small Python/Tkinter
desktop app that invokes the same engine with argument lists and JSON output.
The app must stay usable while scanning or comparing large files.

1. Establish the baseline and add behavioral tests for JSON scan/preview,
   collision-safe moves, exact duplicate groups, and safe recoverable undo.
2. Give the engine readable functions and a documented JSON command interface.
   Preview records exact destinations and a folder snapshot; organization checks
   the snapshot before moving. Never overwrite files or follow symlinks.
3. Journal each proposed move before changing files. Validate the entire journal
   before undo, keep unresolved recovery records, and use only validated relative
   paths within the selected folder. Exclude hidden, configuration and app files.
4. Add the desktop workspace: folder picker, file/size summary, searchable and
   sortable file table, exact destination preview, report-only duplicates, Undo,
   clear progress/error/empty states and a queue-based background worker.
5. Test the real engine, subprocess boundary and desktop behavior. Review the
   resizable interface in a real Tk display. Document setup, Windows commands,
   recovery behavior and the deliberate top-level-only scope.

No framework, package installation, recursive organization or deletion feature is
needed. Recovery protects normal desktop use and interruption; this is not a
shared-folder security boundary or a power-loss-safe transactional filesystem.

Validation: warning-enabled C++ build, full Python unittest discovery, Tk smoke
and interaction tests under Xvfb, then local git diff review and commit.
