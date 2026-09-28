"""A small Tkinter workspace for the C++ FileForge engine. No pip packages needed."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk
from typing import Callable

BACKGROUND = "#F3F5F7"
INK = "#1B2B38"
MUTED = "#526476"
ACCENT = "#176B54"
SIDEBAR = "#152A35"


def format_size(value: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def display_name(value: str) -> str:
    """Keep unusual names on one readable table row; the engine gets the original."""
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


class EngineError(RuntimeError):
    pass


class EngineClient:
    def __init__(self, binary: Path | None = None):
        self.binary = Path(binary) if binary else Path(__file__).with_name("fileforge.exe" if os.name == "nt" else "fileforge")

    def run(self, command: str, folder: Path, snapshot: str | None = None) -> dict:
        if not self.binary.is_file():
            raise EngineError("Compile the C++ engine first. See the README, then place fileforge next to this app.")
        args = [str(self.binary.resolve()), "--json", command, str(folder)]
        if snapshot is not None:
            args.extend(["--snapshot", snapshot])
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, UnicodeError) as error:
            raise EngineError(f"Could not run FileForge: {error}") from error
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise EngineError("The engine returned an unreadable response. Recompile it from this version of the source.") from error
        if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
            raise EngineError("Unexpected engine response. Recompile the engine from this version of the source.")
        if result.returncode or not data["ok"]:
            raise EngineError(data.get("error", "The engine could not finish this operation."))
        return data


class TaskRunner:
    """Workers only put results on a queue. Tk is touched exclusively by the UI."""
    def __init__(self):
        self.results = queue.Queue()
        self.busy = False

    def start(self, work: Callable) -> bool:
        if self.busy:
            return False
        self.busy = True

        def worker():
            try:
                self.results.put((work(), None))
            except Exception as error:
                self.results.put((None, error))

        threading.Thread(target=worker, daemon=True).start()
        return True

    def poll(self):
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            return None
        self.busy = False
        return result


class FileForgeApp:
    def __init__(self, root: tk.Tk, client: EngineClient | None = None):
        self.root = root
        self.client = client or EngineClient()
        self.runner = TaskRunner()
        self.folder: Path | None = None
        self.scan_data: dict | None = None
        self.preview_data: dict | None = None
        self.on_result: Callable | None = None
        self.sort_key, self.sort_reverse = "name", False
        self.active_page = "files"
        self.details = ""
        self.poll_id = None
        self.root.title("FileForge — File workspace")
        self.root.geometry("1180x800")
        self.root.minsize(960, 650)
        self.root.configure(background=BACKGROUND)
        self._styles()
        self._build()
        self.root.bind("<Control-o>", lambda _: self.choose_folder())
        self.root.bind("<Control-r>", lambda _: self.refresh())
        self.root.bind("<Control-f>", self.focus_search)
        self.root.bind("<Escape>", lambda _: self.search_var.set(""))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._set_controls()
        self.poll_id = self.root.after(60, self._poll)
        # Cancels the scheduled callback when a host/test destroys the window.
        self.root.bind("<Destroy>", self._destroyed, add=True)

    def _styles(self):
        family = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
        self.ui_family = family
        for named in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            font.nametofont(named).configure(family=family, size=10)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BACKGROUND)
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background=BACKGROUND, foreground=INK)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Card.TLabel", background="white")
        style.configure("CardMuted.TLabel", background="white", foreground=MUTED)
        style.configure("Title.TLabel", font=(family, 25, "bold"))
        style.configure("Section.TLabel", font=(family, 15, "bold"))
        style.configure("Number.TLabel", background="white", font=(family, 23, "bold"))
        style.configure("TButton", padding=(13, 9), font=(family, 10), background="white", foreground=INK,
                        bordercolor="#CED8DE", lightcolor="white", darkcolor="white", focuscolor=ACCENT)
        style.map("TButton", background=[("active", "#E8EEF1")], foreground=[("disabled", "#85929C")])
        style.configure("Primary.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("Primary.TButton", background=[("disabled", "#DBE5E0"), ("active", "#10513F")],
                  foreground=[("disabled", "#586F65"), ("!disabled", "white")])
        style.configure("Nav.TButton", background=SIDEBAR, foreground="#D6E3EA", borderwidth=0,
                        anchor="w", padding=(16, 12), lightcolor=SIDEBAR, darkcolor=SIDEBAR)
        style.map("Nav.TButton", background=[("active", "#29424F")], foreground=[("disabled", "#7F969F")])
        style.configure("Selected.Nav.TButton", background="#294A50", foreground="white")
        style.map("Selected.Nav.TButton", background=[("active", "#355D62")])
        style.configure("TEntry", padding=9, fieldbackground="white", bordercolor="#CED8DE")
        style.configure("TCombobox", padding=8, fieldbackground="white", bordercolor="#CED8DE")
        style.configure("Treeview", background="white", fieldbackground="white", foreground=INK,
                        rowheight=34, borderwidth=0, font=(family, 10))
        style.configure("Treeview.Heading", background="#EAF0F3", foreground=MUTED,
                        font=(family, 9, "bold"), padding=(9, 10), relief="flat")
        style.map("Treeview", background=[("selected", "#DCEFE7")], foreground=[("selected", "#124C3B")])
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#E7EEEB", borderwidth=0)

    def _build(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        sidebar = tk.Frame(self.root, background=SIDEBAR, width=210)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(6, weight=1)
        brand = tk.Frame(sidebar, background=SIDEBAR)
        brand.grid(row=0, column=0, sticky="ew", padx=22, pady=(28, 30))
        tk.Label(brand, text="F", font=(self.ui_family, 17, "bold"), background="#D7E9DD",
                 foreground="#153C32", width=2, pady=3).pack(side="left")
        tk.Label(brand, text="FileForge", font=(self.ui_family, 14, "bold"), background=SIDEBAR,
                 foreground="white").pack(side="left", padx=(9, 0))
        tk.Label(sidebar, text="YOUR WORKSPACE", background=SIDEBAR, foreground="#91ABB7",
                 font=(self.ui_family, 8, "bold"), anchor="w").grid(row=1, column=0, sticky="ew", padx=26, pady=(0, 12))
        self.nav_buttons = {}
        for index, (key, label, action) in enumerate((
            ("files", "01    All files", lambda: self.show_page("files")),
            ("preview", "02    Preview moves", self.show_preview),
            ("duplicates", "03    Exact duplicates", self.find_duplicates),
        ), start=2):
            button = ttk.Button(sidebar, text=label, command=action, style="Nav.TButton")
            button.grid(row=index, column=0, sticky="ew", padx=12, pady=3)
            self.nav_buttons[key] = button
        self.undo_button = ttk.Button(sidebar, text="Undo last organization", command=self.undo_files, style="Nav.TButton")
        self.undo_button.grid(row=5, column=0, sticky="ew", padx=12, pady=(24, 0))
        tk.Label(sidebar, text="A little order.\nA lot more space.", justify="left", anchor="w", background=SIDEBAR,
                 foreground="#E4EDEC", font=(self.ui_family, 11)).grid(row=7, column=0, sticky="ew", padx=26, pady=(0, 16))
        tk.Label(sidebar, text="C++ engine · Python desktop\nv2.0  /  LOCAL FILES ONLY", justify="left", background=SIDEBAR,
                 foreground="#91ABB7", font=(self.ui_family, 8)).grid(row=8, column=0, sticky="w", padx=26, pady=(0, 24))

        main = ttk.Frame(self.root, padding=(28, 25, 28, 18))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)
        header = ttk.Frame(main)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Your files, in order.", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="See what’s here. Preview every move. Organize with confidence.",
                  style="Muted.TLabel").pack(anchor="w", pady=(5, 18))
        picker = ttk.Frame(main, style="Card.TFrame", padding=14)
        picker.grid(row=1, column=0, sticky="ew")
        picker.columnconfigure(0, weight=1)
        ttk.Label(picker, text="WORKING FOLDER", style="CardMuted.TLabel", font=(self.ui_family, 8, "bold")).grid(row=0, column=0, sticky="w")
        self.folder_var = tk.StringVar(value="Choose a folder to get started")
        self.folder_entry = ttk.Entry(picker, textvariable=self.folder_var, state="readonly", takefocus=True)
        self.folder_entry.grid(row=1, column=0, sticky="ew", pady=(5, 0), padx=(0, 12))
        self.choose_button = ttk.Button(picker, text="Choose folder", command=self.choose_folder, style="Primary.TButton")
        self.choose_button.grid(row=1, column=1, padx=(0, 8), pady=(5, 0))
        self.refresh_button = ttk.Button(picker, text="Refresh", command=self.refresh)
        self.refresh_button.grid(row=1, column=2, pady=(5, 0))
        metrics = ttk.Frame(main)
        metrics.grid(row=2, column=0, sticky="ew", pady=18)
        self.metric_vars = []
        for index, (label, hint) in enumerate((("FILES TO ORGANIZE", "Top-level files"), ("TOTAL SIZE", "Across eligible files"), ("FILE CATEGORIES", "Sorted automatically"))):
            metrics.columnconfigure(index, weight=1, uniform="metrics")
            card = ttk.Frame(metrics, padding=(17, 13), style="Card.TFrame")
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 5, 0 if index == 2 else 5))
            ttk.Label(card, text=label, style="CardMuted.TLabel", font=(self.ui_family, 8, "bold")).pack(anchor="w")
            variable = tk.StringVar(value="—")
            self.metric_vars.append(variable)
            ttk.Label(card, textvariable=variable, style="Number.TLabel").pack(anchor="w", pady=(3, 2))
            ttk.Label(card, text=hint, style="CardMuted.TLabel", font=(self.ui_family, 8)).pack(anchor="w")
        self.scope_var = tk.StringVar(value="Top-level files only. Hidden files, settings and symlinks stay where they are.")
        ttk.Label(main, textvariable=self.scope_var, style="Muted.TLabel", wraplength=820).grid(row=3, column=0, sticky="w", pady=(0, 14))
        self.pages = {}
        for name in ("files", "preview", "duplicates"):
            frame = ttk.Frame(main)
            frame.grid(row=4, column=0, sticky="nsew")
            frame.columnconfigure(0, weight=1)
            self.pages[name] = frame
        self._build_files()
        self._build_preview()
        self._build_duplicates()
        footer = ttk.Frame(main)
        footer.grid(row=5, column=0, sticky="ew", pady=(15, 0))
        footer.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Ready when you are. Choose a folder to see your files.")
        self.status_label = ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel", wraplength=760)
        self.status_label.grid(row=0, column=0, sticky="w")
        self.details_button = ttk.Button(footer, text="Details", command=self.show_details)
        self.details_button.grid(row=0, column=1, padx=(10, 0))
        self.details_button.grid_remove()
        self.progress = ttk.Progressbar(footer, mode="indeterminate", maximum=100)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.progress.grid_remove()
        self.show_page("files")

    def _table(self, parent, columns, row, tree=False):
        container = ttk.Frame(parent, style="Card.TFrame")
        container.grid(row=row, column=0, sticky="nsew")
        parent.rowconfigure(row, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        table = ttk.Treeview(container, columns=[item[0] for item in columns], show="tree headings" if tree else "headings", selectmode="extended")
        for key, label, width in columns:
            table.heading(key, text=label, anchor="w")
            table.column(key, width=width, minwidth=75, anchor="w", stretch=key not in ("size", "category"))
        table.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(container, orient="vertical", command=table.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(container, orient="horizontal", command=table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.tag_configure("alternate", background="#F7F9FA")
        return table

    def _build_files(self):
        page = self.pages["files"]
        top = ttk.Frame(page)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(top, text="All files", style="Section.TLabel").pack(side="left")
        self.preview_button = ttk.Button(top, text="Preview organization →", command=self.show_preview, style="Primary.TButton")
        self.preview_button.pack(side="right")
        filters = ttk.Frame(page)
        filters.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        filters.columnconfigure(1, weight=1)
        ttk.Label(filters, text="Search", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 9))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filters, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self.category_var = tk.StringVar(value="All categories")
        self.category_filter = ttk.Combobox(filters, textvariable=self.category_var, state="readonly", width=17, values=("All categories",))
        self.category_filter.grid(row=0, column=2)
        self.search_var.trace_add("write", lambda *_: self.render_files())
        self.category_var.trace_add("write", lambda *_: self.render_files())
        self.files_tree = self._table(page, (("name", "NAME ↑", 380), ("category", "CATEGORY", 130), ("size", "SIZE", 100)), 2)
        self.files_empty_panel = ttk.Frame(page, style="Card.TFrame")
        self.files_empty_panel.grid(row=2, column=0, sticky="nsew")
        welcome = ttk.Frame(self.files_empty_panel, style="Card.TFrame", padding=24)
        welcome.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(welcome, text="Start with a folder", style="Card.TLabel",
                  font=(self.ui_family, 20, "bold")).pack(pady=(0, 10))
        ttk.Label(welcome, text="Choose a folder to see its files, check duplicates, and preview every move.",
                  style="CardMuted.TLabel", wraplength=430, justify="center").pack(pady=(0, 20))
        ttk.Button(welcome, text="Choose a folder", command=self.choose_folder,
                   style="Primary.TButton").pack()
        for column in ("name", "category", "size"):
            self.files_tree.heading(column, command=lambda key=column: self.sort_files(key))
        self.files_empty_var = tk.StringVar(value="Choose a folder above. Your eligible files will appear here.")
        self.files_count_label = ttk.Label(page, textvariable=self.files_empty_var, style="Muted.TLabel")
        self.files_count_label.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.files_count_label.grid_remove()
        self.render_files()

    def _build_preview(self):
        page = self.pages["preview"]
        ttk.Label(page, text="Review every move", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.preview_hint_var = tk.StringVar(value="Preview exact destinations before organizing.")
        ttk.Label(page, textvariable=self.preview_hint_var, style="Muted.TLabel", wraplength=790).grid(row=1, column=0, sticky="w", pady=(7, 14))
        self.preview_tree = self._table(page, (("source", "CURRENT NAME", 320), ("destination", "DESTINATION", 400)), 2)
        bar = ttk.Frame(page)
        bar.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(bar, text="Existing names are kept. New files get a numbered name.", style="Muted.TLabel").pack(side="left")
        self.organize_button = ttk.Button(bar, text="Organize files", command=self.organize_files, style="Primary.TButton")
        self.organize_button.pack(side="right", padx=(8, 0))

    def _build_duplicates(self):
        page = self.pages["duplicates"]
        top = ttk.Frame(page)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Exact duplicates", style="Section.TLabel").pack(side="left")
        self.duplicates_button = ttk.Button(top, text="Compare again", command=self.find_duplicates)
        self.duplicates_button.pack(side="right")
        self.duplicates_hint_var = tk.StringVar(value="Matching size and matching contents. This view only reports files.")
        ttk.Label(page, textvariable=self.duplicates_hint_var, style="Muted.TLabel", wraplength=790).grid(row=1, column=0, sticky="w", pady=(7, 14))
        self.duplicates_tree = self._table(page, (("size", "SIZE EACH", 110),), 2, tree=True)
        self.duplicates_tree.heading("#0", text="DUPLICATE GROUP / FILE NAME", anchor="w")
        self.duplicates_tree.column("#0", width=540, minwidth=240, stretch=True)
        ttk.Label(page, text="Nothing is deleted or moved here. Compare files before removing anything yourself.",
                  style="Muted.TLabel", wraplength=790).grid(row=3, column=0, sticky="w", pady=(12, 0))

    def show_page(self, name):
        self.active_page = name
        self.pages[name].tkraise()
        for key, button in self.nav_buttons.items():
            button.configure(style="Selected.Nav.TButton" if key == name else "Nav.TButton")

    def focus_search(self, _event=None):
        self.show_page("files")
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")
        return "break"

    def _set_controls(self):
        busy, ready = self.runner.busy, self.scan_data is not None
        def state(button, enabled):
            button.state(["!disabled"] if enabled and not busy else ["disabled"])
        state(self.choose_button, True)
        state(self.refresh_button, self.folder is not None)
        state(self.preview_button, ready and bool(self.scan_data["files"]))
        state(self.duplicates_button, ready)
        state(self.undo_button, ready and self.scan_data.get("undo_available", False))
        for name, button in self.nav_buttons.items():
            state(button, name == "files" or ready)
        state(self.organize_button, bool(self.preview_data and self.preview_data["moves"] and not self.preview_data["blockers"]))

    def _status(self, text, error=False, details=""):
        self.status_var.set(text)
        self.status_label.configure(foreground="#A2352E" if error else MUTED)
        self.details = details
        if details:
            self.details_button.grid()
        else:
            self.details_button.grid_remove()

    def _run(self, work, callback, text):
        if not self.runner.start(work):
            return
        self.on_result = callback
        self._status(text)
        self.progress.grid()
        self.progress.start(12)
        self._set_controls()

    def _poll(self):
        result = self.runner.poll()
        if result is not None:
            value, error = result
            self.progress.stop()
            self.progress.grid_remove()
            callback, self.on_result = self.on_result, None
            if error:
                self._status(str(error), error=True, details=str(error))
            elif callback:
                callback(value)
            self._set_controls()
        self.poll_id = self.root.after(60, self._poll)

    def choose_folder(self):
        if self.runner.busy:
            return
        folder = filedialog.askdirectory(title="Choose a folder to organize", mustexist=True,
                                         initialdir=str(self.folder) if self.folder and self.folder.exists() else None)
        if folder:
            self.load_folder(Path(folder))

    def load_folder(self, folder):
        if self.runner.busy:
            return
        self.folder = Path(folder).expanduser().absolute()
        self.folder_var.set(str(self.folder))
        self.scan_data = self.preview_data = None
        self.search_var.set("")
        self.category_var.set("All categories")
        self.preview_tree.delete(*self.preview_tree.get_children())
        self.duplicates_tree.delete(*self.duplicates_tree.get_children())
        self.render_files()
        for variable in self.metric_vars:
            variable.set("—")
        selected = self.folder
        self.show_page("files")
        self._run(lambda: self.client.run("scan", selected), self._apply_scan, "Scanning folder…")

    def refresh(self):
        if self.folder and not self.runner.busy:
            self.load_folder(self.folder)

    def _apply_scan(self, data):
        self.scan_data = data
        self.folder = Path(data["folder"])
        self.folder_var.set(str(self.folder))
        for variable, value in zip(self.metric_vars, (str(data["file_count"]), format_size(data["total_bytes"]), str(len(data["categories"])))):
            variable.set(value)
        categories = ["All categories", *sorted(data["categories"])]
        self.category_filter.configure(values=categories)
        if self.category_var.get() not in categories:
            self.category_var.set("All categories")
        self.scope_var.set(f"{data['skipped_count']} entries left in place · Folders, hidden files, settings and symlinks are excluded.")
        self.render_files()
        if data["undo_available"]:
            self._status("An organization can be undone. Use Undo before organizing more files.")
        elif data["blockers"]:
            self._status(data["blockers"][0], error=True, details="\n".join(data["blockers"]))
        elif not data["files"]:
            self._status("All clear. There are no eligible files in this folder.")
        else:
            self._status(f"{data['file_count']} files ready to review. Preview organization to see every destination.")

    def render_files(self):
        if not hasattr(self, "files_tree"):
            return
        self.files_tree.delete(*self.files_tree.get_children())
        if not self.scan_data:
            self.files_empty_var.set("Choose a folder above. Your eligible files will appear here.")
            self.files_tree.master.grid_remove()
            self.files_empty_panel.grid()
            self.files_count_label.grid_remove()
            return
        self.files_empty_panel.grid_remove()
        self.files_tree.master.grid()
        self.files_count_label.grid()
        query = self.search_var.get().casefold().strip()
        category = self.category_var.get()
        files = [item for item in self.scan_data["files"] if query in item["name"].casefold()
                 and (category == "All categories" or item["category"] == category)]
        files.sort(key=lambda item: (item[self.sort_key].casefold() if isinstance(item[self.sort_key], str) else item[self.sort_key], item["name"]), reverse=self.sort_reverse)
        for index, item in enumerate(files):
            self.files_tree.insert("", "end", values=(display_name(item["name"]), item["category"], format_size(item["size"])), tags=("alternate",) if index % 2 else ())
        self.files_empty_var.set(f"Showing {len(files)} of {self.scan_data['file_count']} files" if files else
                                "No matches. Clear the search or choose another category." if self.scan_data["files"] else
                                "Nothing to organize. Subfolders and excluded files stay in place.")
        for key in ("name", "category", "size"):
            suffix = (" ↓" if self.sort_reverse else " ↑") if self.sort_key == key else ""
            self.files_tree.heading(key, text=key.upper() + suffix)

    def sort_files(self, key):
        self.sort_reverse = not self.sort_reverse if self.sort_key == key else False
        self.sort_key = key
        self.render_files()

    def show_preview(self):
        if not self.folder or not self.scan_data or self.runner.busy:
            return
        selected = self.folder
        self.show_page("preview")
        self.preview_data = None
        self.preview_tree.delete(*self.preview_tree.get_children())
        self.preview_hint_var.set("Checking the folder and reserving exact destination names…")

        def ready(data):
            self.preview_data = data
            self._apply_scan(data)
            for index, move in enumerate(data["moves"]):
                self.preview_tree.insert("", "end", values=(display_name(move["source"]), display_name(move["destination"])), tags=("alternate",) if index % 2 else ())
            self.preview_hint_var.set(data["blockers"][0] if data["blockers"] else
                                      f"{len(data['moves'])} files will move into category folders. Review the destinations below.")
            if not data["blockers"]:
                self._status("Preview ready. No files have been moved.")
        self._run(lambda: self.client.run("preview", selected), ready, "Preparing exact destinations…")

    def organize_files(self):
        if self.runner.busy or not self.preview_data or not self.preview_data["moves"] or self.preview_data["blockers"]:
            return
        count = len(self.preview_data["moves"])
        if not messagebox.askyesno("Organize these files?", f"Move {count} files into the destinations shown?\n\nExisting files will be kept. You can undo this organization.", parent=self.root, default="no"):
            return
        selected, snapshot = self.folder, self.preview_data["snapshot"]
        self.preview_data = None

        def work():
            operation = self.client.run("organize", selected, snapshot)
            return operation, self.client.run("scan", selected)
        self._run(work, lambda result: self._after_change("Organized", "moved", result), "Organizing files. Please keep this window open…")

    def undo_files(self):
        if self.runner.busy or not self.scan_data or not self.scan_data["undo_available"]:
            return
        if not messagebox.askyesno("Undo last organization?", "Bring the organized files back to this folder?\n\nIf a name is now taken, the restored file gets a numbered name.", parent=self.root, default="no"):
            return
        selected = self.folder

        def work():
            operation = self.client.run("undo", selected)
            return operation, self.client.run("scan", selected)
        self._run(work, lambda result: self._after_change("Restored", "restored", result), "Restoring files. Please keep this window open…")

    def _after_change(self, label, key, result):
        operation, data = result
        self.preview_data = None
        self.preview_tree.delete(*self.preview_tree.get_children())
        self.duplicates_tree.delete(*self.duplicates_tree.get_children())
        self._apply_scan(data)
        self.show_page("files")
        warnings = operation["warnings"]
        message = f"{label} {operation[key]} files."
        if warnings:
            message += " Some entries need attention. Open Details for recovery information."
        elif data["undo_available"]:
            message += " Undo is available in the sidebar."
        else:
            message += " Your files are ready."
        self._status(message, error=bool(warnings), details="\n\n".join(warnings))

    def find_duplicates(self):
        if not self.folder or not self.scan_data or self.runner.busy:
            return
        selected = self.folder
        self.show_page("duplicates")
        self.duplicates_tree.delete(*self.duplicates_tree.get_children())
        self.duplicates_hint_var.set("Comparing file contents. Large files may take a little longer…")

        def ready(data):
            for index, group in enumerate(data["groups"], start=1):
                parent = self.duplicates_tree.insert("", "end", text=f"Group {index} · {len(group['files'])} identical files", values=(format_size(group["size"]),), open=True)
                for name in group["files"]:
                    self.duplicates_tree.insert(parent, "end", text=display_name(name), values=(format_size(group["size"]),))
            if data["groups"]:
                self.duplicates_hint_var.set(f"{len(data['groups'])} groups · {data['duplicate_count']} extra copies · {format_size(data['reclaimable_bytes'])} in extra copies")
                self._status("Comparison complete. This report does not delete or move any files.")
            else:
                self.duplicates_hint_var.set("No exact duplicates found among the eligible top-level files.")
                self._status("Comparison complete. Every eligible file has unique contents.")
        self._run(lambda: self.client.run("duplicates", selected), ready, "Comparing files byte for byte…")

    def show_details(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("FileForge — Operation details")
        dialog.geometry("690x360")
        dialog.transient(self.root)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        text = tk.Text(dialog, wrap="word", padx=18, pady=18, background="white", foreground=INK)
        text.grid(row=0, column=0, sticky="nsew")
        text.insert("1.0", self.details)
        text.configure(state="disabled")
        scrollbar = ttk.Scrollbar(dialog, command=text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scrollbar.set)
        ttk.Button(dialog, text="Close", command=dialog.destroy).grid(row=1, column=0, sticky="e", padx=12, pady=12)
        dialog.bind("<Escape>", lambda _: dialog.destroy())

    def _destroyed(self, event):
        if event.widget == self.root and self.poll_id:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None

    def close(self):
        if self.runner.busy:
            messagebox.showinfo("Operation in progress", "Please wait for the current operation to finish before closing FileForge.", parent=self.root)
            return
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="FileForge desktop workspace")
    parser.add_argument("folder", nargs="?", type=Path, help="Optional folder to scan on startup")
    args = parser.parse_args()
    root = tk.Tk()
    app = FileForgeApp(root)
    if args.folder:
        root.after(0, lambda: app.load_folder(args.folder))
    root.mainloop()


if __name__ == "__main__":
    main()
