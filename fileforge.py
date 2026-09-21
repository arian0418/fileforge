import hashlib
import json
import shutil
import tkinter as tk
from collections import defaultdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".csv", ".xlsx", ".pptx"},
    "Videos": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
    "Audio": {".mp3", ".wav", ".m4a", ".flac"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Code": {".py", ".java", ".cpp", ".c", ".h", ".js", ".html", ".css", ".json"},
}
UNDO_FILE = Path.home() / ".fileforge_last_action.json"

def category_for(path):
    suffix = path.suffix.lower()
    for category, extensions in CATEGORIES.items():
        if suffix in extensions:
            return category
    return "Other"

def format_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024

def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()

class FileForgeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FileForge")
        self.root.geometry("1000x650")
        self.folder = None
        self.files = []
        self.build_ui()

    def build_ui(self):
        top = ttk.Frame(self.root, padding=16)
        top.pack(fill="x")
        ttk.Label(top, text="FileForge", font=("Segoe UI", 22, "bold")).pack(side="left")
        ttk.Button(top, text="Choose Folder", command=self.choose_folder).pack(side="right")

        self.folder_label = ttk.Label(self.root, text="Choose a folder to begin.", padding=(16, 0))
        self.folder_label.pack(fill="x")

        stats = ttk.Frame(self.root, padding=16)
        stats.pack(fill="x")
        self.file_count = ttk.Label(stats, text="Files: 0")
        self.file_count.pack(side="left", padx=(0, 25))
        self.total_size = ttk.Label(stats, text="Storage: 0 B")
        self.total_size.pack(side="left", padx=(0, 25))
        self.duplicate_count = ttk.Label(stats, text="Duplicates: not scanned")
        self.duplicate_count.pack(side="left")

        controls = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        controls.pack(fill="x")
        ttk.Button(controls, text="Scan Folder", command=self.scan).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Find Duplicates", command=self.find_duplicates).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Preview Organization", command=self.preview).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Organize Files", command=self.organize).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Undo Last Move", command=self.undo).pack(side="left")

        columns = ("name", "type", "size", "category")
        self.table = ttk.Treeview(self.root, columns=columns, show="headings")
        for column, width in zip(columns, (430, 100, 120, 160)):
            self.table.heading(column, text=column.title())
            self.table.column(column, width=width)
        self.table.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def choose_folder(self):
        selected = filedialog.askdirectory()
        if selected:
            self.folder = Path(selected)
            self.folder_label.config(text=str(self.folder))
            self.scan()

    def scan(self):
        if not self.folder:
            messagebox.showinfo("FileForge", "Choose a folder first.")
            return
        self.files = [p for p in self.folder.iterdir() if p.is_file()]
        for row in self.table.get_children():
            self.table.delete(row)
        total = 0
        for path in sorted(self.files, key=lambda p: p.name.lower()):
            size = path.stat().st_size
            total += size
            self.table.insert("", "end", values=(path.name, path.suffix or "No extension", format_size(size), category_for(path)))
        self.file_count.config(text=f"Files: {len(self.files)}")
        self.total_size.config(text=f"Storage: {format_size(total)}")
        self.duplicate_count.config(text="Duplicates: not scanned")

    def duplicate_groups(self):
        by_size = defaultdict(list)
        for path in self.files:
            by_size[path.stat().st_size].append(path)
        by_hash = defaultdict(list)
        for same_size in by_size.values():
            if len(same_size) > 1:
                for path in same_size:
                    by_hash[file_hash(path)].append(path)
        return [group for group in by_hash.values() if len(group) > 1]

    def find_duplicates(self):
        if not self.files:
            self.scan()
        groups = self.duplicate_groups()
        extras = sum(len(group) - 1 for group in groups)
        self.duplicate_count.config(text=f"Duplicates: {extras}")
        if not groups:
            messagebox.showinfo("Duplicates", "No duplicate files found.")
            return
        details = []
        for number, group in enumerate(groups, 1):
            details.append(f"Group {number}:\n" + "\n".join(f"  {p.name}" for p in group))
        messagebox.showinfo("Duplicate Files", "\n\n".join(details)[:4000])

    def moves(self):
        return [(path, self.folder / category_for(path) / path.name) for path in self.files]

    def preview(self):
        if not self.folder:
            messagebox.showinfo("FileForge", "Choose a folder first.")
            return
        self.scan()
        counts = defaultdict(int)
        for source, _ in self.moves():
            counts[category_for(source)] += 1
        text = "\n".join(f"{category}: {count} file(s)" for category, count in sorted(counts.items()))
        messagebox.showinfo("Organization Preview", text or "There are no files to organize.")

    def organize(self):
        if not self.folder:
            messagebox.showinfo("FileForge", "Choose a folder first.")
            return
        self.scan()
        planned = self.moves()
        if not planned:
            return
        if not messagebox.askyesno("Organize Files", f"Move {len(planned)} file(s) into category folders?"):
            return
        completed = []
        try:
            for source, destination in planned:
                destination.parent.mkdir(exist_ok=True)
                if destination.exists():
                    stem, suffix = destination.stem, destination.suffix
                    number = 1
                    while destination.exists():
                        destination = destination.parent / f"{stem}_{number}{suffix}"
                        number += 1
                shutil.move(str(source), str(destination))
                completed.append({"from": str(source), "to": str(destination)})
            UNDO_FILE.write_text(json.dumps(completed, indent=2), encoding="utf-8")
            self.scan()
            messagebox.showinfo("FileForge", f"Organized {len(completed)} file(s).")
        except OSError as error:
            messagebox.showerror("FileForge", f"Could not finish organizing files:\n{error}")

    def undo(self):
        if not UNDO_FILE.exists():
            messagebox.showinfo("Undo", "There is no saved organization action to undo.")
            return
        actions = json.loads(UNDO_FILE.read_text(encoding="utf-8"))
        restored = 0
        for action in reversed(actions):
            source, destination = Path(action["from"]), Path(action["to"])
            if destination.exists() and not source.exists():
                shutil.move(str(destination), str(source))
                restored += 1
        UNDO_FILE.unlink(missing_ok=True)
        if self.folder:
            self.scan()
        messagebox.showinfo("Undo", f"Restored {restored} file(s).")

if __name__ == "__main__":
    root = tk.Tk()
    FileForgeApp(root)
    root.mainloop()
