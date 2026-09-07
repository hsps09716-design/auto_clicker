from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import threading
import time
import tempfile
import tkinter as tk
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from ctypes import wintypes


APP_NAME = "Auto Clicker"
APP_VERSION = "1.2.0"


@dataclass
class ClickStep:
    x: int
    y: int
    delay_ms: int


class WinPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MouseHookStruct(ctypes.Structure):
    _fields_ = [
        ("pt", WinPoint),
        ("mouseData", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MouseRecorder:
    WH_MOUSE_LL = 14
    WM_LBUTTONDOWN = 0x0201
    WM_QUIT = 0x0012

    def __init__(self, on_click):
        self.on_click = on_click
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.hook = None
        self.callback_ref = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, self.WM_QUIT, 0, 0)
        self.thread_id = None

    def _run(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        callback_type = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.restype = wintypes.LPARAM

        def low_level_proc(n_code, w_param, l_param):
            if n_code >= 0 and w_param == self.WM_LBUTTONDOWN:
                info = ctypes.cast(l_param, ctypes.POINTER(MouseHookStruct)).contents
                self.on_click(int(info.pt.x), int(info.pt.y), time.perf_counter())
            return user32.CallNextHookEx(self.hook, n_code, w_param, l_param)

        self.callback_ref = callback_type(low_level_proc)
        self.hook = user32.SetWindowsHookExW(self.WH_MOUSE_LL, self.callback_ref, 0, 0)
        if not self.hook:
            self.thread_id = None
            return
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self.hook)
        self.hook = None
        self.thread_id = None


class AutoClickerApp:
    BG = "#0c1017"
    PANEL = "#141a24"
    PANEL_2 = "#1a2230"
    BORDER = "#2a3546"
    TEXT = "#edf2f7"
    MUTED = "#8f9bad"
    ACCENT = "#ff9f43"
    ACCENT_ACTIVE = "#e9872e"
    BLUE = "#63a8ff"
    GREEN = "#45d19a"
    RED = "#ff6b6b"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.steps: list[ClickStep] = []
        self.recording = False
        self.playing = False
        self.last_record_time: float | None = None
        self.stop_event = threading.Event()
        self.ui_events: queue.Queue = queue.Queue()
        self.record_hotkey_down = False
        self.stop_hotkey_down = False
        self.recorder = MouseRecorder(self._record_click_from_hook)

        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1100x680")
        self.root.minsize(900, 590)
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._configure_style()
        self._build_ui()
        self._load_autosave()
        self._poll()

    def _configure_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=self.PANEL, fieldbackground=self.PANEL,
                        foreground=self.TEXT, rowheight=38, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=self.PANEL_2, foreground=self.MUTED,
                        relief="flat", padding=(10, 10), font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#2d4057")], foreground=[("selected", self.TEXT)])
        style.map("Treeview.Heading", background=[("active", self.PANEL_2)])
        style.configure("TCombobox", fieldbackground=self.PANEL_2, background=self.PANEL_2,
                        foreground=self.TEXT, arrowcolor=self.TEXT, bordercolor=self.BORDER)

    def _build_ui(self):
        tk.Frame(self.root, bg=self.ACCENT, height=3).pack(fill="x")
        header = tk.Frame(self.root, bg=self.BG, padx=24, pady=16)
        header.pack(fill="x")
        profile_area = tk.Frame(header, bg=self.BG)
        profile_area.pack(side="left", fill="x", expand=True)
        tk.Label(profile_area, text="PROFILE", bg=self.BG, fg=self.MUTED,
                 font=("Segoe UI Semibold", 9)).pack(side="left", padx=(0, 10))
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(profile_area, textvariable=self.profile_var,
                                          state="readonly", width=24, font=("Segoe UI", 10))
        self.profile_combo.pack(side="left", ipady=5)
        for text, command in (("LOAD", self.load_selected_profile),
                              ("SAVE AS", self.save_profile_as),
                              ("DELETE", self.delete_profile)):
            tk.Button(profile_area, text=text, command=command, bg=self.PANEL_2,
                      fg=self.RED if text == "DELETE" else self.TEXT, relief="flat",
                      activebackground="#253247", activeforeground=self.TEXT, cursor="hand2",
                      font=("Segoe UI Semibold", 8), padx=11, pady=7).pack(side="left", padx=(7, 0))
        self._refresh_profiles()

        self.status_badge = tk.Label(header, text="●  READY", bg=self.PANEL_2, fg=self.GREEN,
                                     padx=14, pady=8, font=("Segoe UI Semibold", 10))
        self.status_badge.pack(side="right")

        body = tk.Frame(self.root, bg=self.BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        left = self._panel(body, width=285)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)

        center = self._panel(body)
        center.pack(side="left", fill="both", expand=True)

        self._build_controls(left)
        self._build_sequence(center)

        footer = tk.Frame(self.root, bg=self.BG)
        footer.pack(fill="x", padx=24, pady=(0, 18))
        tk.Label(footer, text="Record: Ctrl + Alt + R    •    Emergency stop: Ctrl + Alt + S", bg=self.BG,
                 fg=self.MUTED, font=("Segoe UI", 9)).pack(side="left")
        self.count_label = tk.Label(footer, text="0 clicks", bg=self.BG, fg=self.MUTED,
                                    font=("Segoe UI", 9))
        self.count_label.pack(side="right")

    def _panel(self, parent, width=None):
        kwargs = {"bg": self.PANEL, "highlightthickness": 1, "highlightbackground": self.BORDER}
        if width:
            kwargs["width"] = width
        return tk.Frame(parent, **kwargs)

    def _section_title(self, parent, text):
        tk.Label(parent, text=text, bg=self.PANEL, fg=self.TEXT,
                 font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=18, pady=(18, 10))

    def _label(self, parent, text):
        tk.Label(parent, text=text, bg=self.PANEL, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(7, 4))

    def _entry(self, parent, variable):
        entry = tk.Entry(parent, textvariable=variable, bg=self.PANEL_2, fg=self.TEXT,
                         insertbackground=self.TEXT, relief="flat", highlightthickness=1,
                         highlightbackground=self.BORDER, highlightcolor=self.ACCENT,
                         font=("Segoe UI", 10))
        entry.pack(fill="x", padx=18, ipady=7)
        return entry

    def _button(self, parent, text, command, accent=False, **pack):
        button = tk.Button(parent, text=text, command=command, relief="flat", cursor="hand2",
                           bg=self.ACCENT if accent else self.PANEL_2,
                           activebackground=self.ACCENT_ACTIVE if accent else "#253247",
                           fg="#101318" if accent else self.TEXT,
                           activeforeground="#101318" if accent else self.TEXT,
                           font=("Segoe UI Semibold", 10), padx=12, pady=9, bd=0)
        button.pack(**pack)
        return button

    def _build_controls(self, parent):
        self._section_title(parent, "ADD CLICK")
        coord_row = tk.Frame(parent, bg=self.PANEL)
        coord_row.pack(fill="x", padx=18)
        self.x_var, self.y_var = tk.StringVar(value="0"), tk.StringVar(value="0")
        for label, var in (("X", self.x_var), ("Y", self.y_var)):
            col = tk.Frame(coord_row, bg=self.PANEL)
            col.pack(side="left", fill="x", expand=True, padx=(0, 6) if label == "X" else (6, 0))
            tk.Label(col, text=label, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w")
            tk.Entry(col, textvariable=var, bg=self.PANEL_2, fg=self.TEXT, insertbackground=self.TEXT,
                     relief="flat", highlightthickness=1, highlightbackground=self.BORDER,
                     highlightcolor=self.ACCENT, font=("Segoe UI", 10)).pack(fill="x", ipady=7)

        self.delay_var = tk.StringVar(value="500")
        self._label(parent, "Delay before click (ms)")
        self._entry(parent, self.delay_var)
        self._button(parent, "◎  CAPTURE CURSOR POSITION", self.capture_position,
                     fill="x", padx=18, pady=(10, 6))
        self._button(parent, "+  ADD TO SEQUENCE", self.add_step, accent=True,
                     fill="x", padx=18, pady=(0, 12))

        tk.Frame(parent, bg=self.BORDER, height=1).pack(fill="x", padx=18, pady=4)
        self._section_title(parent, "RECORD & PLAY")
        self.record_btn = self._button(parent, "●  RECORD   Ctrl + Alt + R", self.toggle_recording,
                                       fill="x", padx=18, pady=(0, 7))
        self.start_delay_var = tk.StringVar(value="3")
        self.repeat_var = tk.StringVar(value="1")
        row = tk.Frame(parent, bg=self.PANEL)
        row.pack(fill="x", padx=18, pady=(4, 8))
        for title, var in (("Start delay", self.start_delay_var), ("Repeat", self.repeat_var)):
            col = tk.Frame(row, bg=self.PANEL)
            col.pack(side="left", fill="x", expand=True, padx=(0, 6) if title == "Start delay" else (6, 0))
            tk.Label(col, text=title, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w")
            tk.Entry(col, textvariable=var, bg=self.PANEL_2, fg=self.TEXT, insertbackground=self.TEXT,
                     relief="flat", highlightthickness=1, highlightbackground=self.BORDER,
                     highlightcolor=self.ACCENT, font=("Segoe UI", 10)).pack(fill="x", ipady=7)
        self.play_btn = self._button(parent, "▶  START PLAYBACK", self.start_playback, accent=True,
                                     fill="x", padx=18, pady=(2, 7))
        self.stop_btn = self._button(parent, "■  STOP   Ctrl + Alt + S", self.stop_playback,
                                     fill="x", padx=18, pady=(0, 12))

    def _build_sequence(self, parent):
        top = tk.Frame(parent, bg=self.PANEL, padx=18, pady=16)
        top.pack(fill="x")
        tk.Label(top, text="CLICK SEQUENCE", bg=self.PANEL, fg=self.TEXT,
                 font=("Segoe UI Semibold", 13)).pack(side="left")
        for text, cmd in (("IMPORT", self.load_file), ("EXPORT", self.save_file), ("CLEAR", self.clear_steps)):
            tk.Button(top, text=text, command=cmd, bg=self.PANEL_2, fg=self.TEXT, relief="flat",
                      activebackground="#253247", activeforeground=self.TEXT, cursor="hand2",
                      font=("Segoe UI", 9), padx=12, pady=6).pack(side="right", padx=(6, 0))

        table_frame = tk.Frame(parent, bg=self.PANEL)
        table_frame.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        columns = ("index", "x", "y", "delay")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        for column, title, width in (("index", "STEP", 60), ("x", "X POSITION", 110),
                                     ("y", "Y POSITION", 110), ("delay", "DELAY", 150)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor="center", stretch=column == "delay")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self.load_selected_into_editor)

        actions = tk.Frame(parent, bg=self.PANEL)
        actions.pack(fill="x", padx=18, pady=(0, 16))
        for text, cmd in (("↑ MOVE UP", lambda: self.move_selected(-1)),
                          ("↓ MOVE DOWN", lambda: self.move_selected(1)),
                          ("APPLY EDIT", self.update_selected),
                          ("DELETE", self.delete_selected)):
            tk.Button(actions, text=text, command=cmd, bg=self.PANEL_2,
                      fg=self.RED if text == "DELETE" else self.TEXT, relief="flat",
                      activebackground="#253247", activeforeground=self.TEXT, cursor="hand2",
                      font=("Segoe UI", 9), padx=12, pady=8).pack(side="left", padx=(0, 7))

        hint = tk.Label(parent, text="Recording captures every left click, its order, and the exact time between clicks.",
                        bg=self.PANEL_2, fg=self.MUTED, anchor="w", padx=14, pady=10,
                        font=("Segoe UI", 9))
        hint.pack(fill="x", padx=18, pady=(0, 18))

    def _parse_int(self, value, name, minimum=None):
        try:
            number = int(value)
        except ValueError:
            raise ValueError(f"{name} must be a whole number.")
        if minimum is not None and number < minimum:
            raise ValueError(f"{name} cannot be less than {minimum}.")
        return number

    def capture_position(self):
        point = WinPoint()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        self.x_var.set(str(point.x))
        self.y_var.set(str(point.y))

    def add_step(self):
        try:
            self.steps.append(ClickStep(self._parse_int(self.x_var.get(), "X"),
                                        self._parse_int(self.y_var.get(), "Y"),
                                        self._parse_int(self.delay_var.get(), "Delay", 0)))
        except ValueError as exc:
            messagebox.showerror("Cannot add click", str(exc))
            return
        self.refresh_tree(select=len(self.steps) - 1)

    def toggle_recording(self):
        if self.playing:
            return
        if self.recording:
            self.recording = False
            self.recorder.stop()
            self.record_btn.config(text="●  RECORD   Ctrl + Alt + R", bg=self.PANEL_2, fg=self.TEXT)
            self.set_status("●  RECORDING SAVED", self.GREEN)
            self._autosave()
        else:
            self.recording = True
            self.last_record_time = None
            self.recorder.start()
            self.record_btn.config(text="■  STOP RECORDING   Ctrl + Alt + R", bg=self.RED, fg="#14171d")
            self.set_status("●  RECORDING", self.RED)

    def _record_click_from_hook(self, x, y, stamp):
        if not self.recording:
            return
        point = WinPoint(x, y)
        clicked_window = ctypes.windll.user32.WindowFromPoint(point)
        root_window = ctypes.windll.user32.GetAncestor(clicked_window, 2)
        if root_window == self.root.winfo_id():
            return
        delay = 0 if self.last_record_time is None else max(0, round((stamp - self.last_record_time) * 1000))
        self.last_record_time = stamp
        self.ui_events.put(("record", x, y, delay))

    def start_playback(self):
        if self.playing or self.recording:
            return
        if not self.steps:
            messagebox.showinfo("No clicks", "Add, record, or load at least one click first.")
            return
        try:
            start_delay = self._parse_int(self.start_delay_var.get(), "Start delay", 0)
            repeat = self._parse_int(self.repeat_var.get(), "Repeat count", 1)
        except ValueError as exc:
            messagebox.showerror("Cannot start playback", str(exc))
            return
        self.playing = True
        self.stop_event.clear()
        self.play_btn.config(state="disabled")
        threading.Thread(target=self._play_worker, args=(start_delay, repeat), daemon=True).start()

    def _play_worker(self, start_delay, repeat):
        for remaining in range(start_delay, 0, -1):
            self.ui_events.put(("status", f"●  STARTING IN {remaining}s", self.ACCENT))
            if self.stop_event.wait(1):
                break
        if not self.stop_event.is_set():
            user32 = ctypes.windll.user32
            for cycle in range(repeat):
                for index, step in enumerate(list(self.steps)):
                    if self.stop_event.wait(step.delay_ms / 1000):
                        break
                    user32.SetCursorPos(step.x, step.y)
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                    self.ui_events.put(("active", index, cycle + 1, repeat))
                if self.stop_event.is_set():
                    break
        self.ui_events.put(("finished", self.stop_event.is_set()))

    def stop_playback(self):
        if self.playing:
            self.stop_event.set()

    def _poll(self):
        while True:
            try:
                event = self.ui_events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "record":
                self.steps.append(ClickStep(event[1], event[2], event[3]))
                self.refresh_tree(select=len(self.steps) - 1)
            elif event[0] == "status":
                self.set_status(event[1], event[2])
            elif event[0] == "active":
                self.refresh_tree(select=event[1])
                self.set_status(f"●  PLAYING  {event[2]}/{event[3]}", self.ACCENT)
            elif event[0] == "finished":
                self.playing = False
                self.play_btn.config(state="normal")
                self.set_status("●  STOPPED" if event[1] else "●  COMPLETE",
                                self.RED if event[1] else self.GREEN)

        if os.name == "nt":
            ctrl_alt = (bool(ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000)
                        and bool(ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000))
            record_hotkey = ctrl_alt and bool(ctypes.windll.user32.GetAsyncKeyState(ord("R")) & 0x8000)
            stop_hotkey = ctrl_alt and bool(ctypes.windll.user32.GetAsyncKeyState(ord("S")) & 0x8000)
            if record_hotkey and not self.record_hotkey_down:
                self.toggle_recording()
            if stop_hotkey and not self.stop_hotkey_down:
                self.stop_playback()
            self.record_hotkey_down, self.stop_hotkey_down = record_hotkey, stop_hotkey
        self.root.after(60, self._poll)

    def refresh_tree(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for i, step in enumerate(self.steps, 1):
            self.tree.insert("", "end", iid=str(i - 1), values=(f"{i:02d}", step.x, step.y, f"{step.delay_ms} ms"))
        if select is not None and 0 <= select < len(self.steps):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))
        self.count_label.config(text=f"{len(self.steps)} click{'s' if len(self.steps) != 1 else ''}")
        self._autosave()

    def selected_index(self):
        selected = self.tree.selection()
        return int(selected[0]) if selected else None

    def load_selected_into_editor(self, _event=None):
        index = self.selected_index()
        if index is None:
            return
        step = self.steps[index]
        self.x_var.set(str(step.x)); self.y_var.set(str(step.y)); self.delay_var.set(str(step.delay_ms))

    def update_selected(self):
        index = self.selected_index()
        if index is None:
            return
        try:
            self.steps[index] = ClickStep(self._parse_int(self.x_var.get(), "X"),
                                          self._parse_int(self.y_var.get(), "Y"),
                                          self._parse_int(self.delay_var.get(), "Delay", 0))
        except ValueError as exc:
            messagebox.showerror("Cannot update click", str(exc)); return
        self.refresh_tree(select=index)

    def delete_selected(self):
        index = self.selected_index()
        if index is not None:
            self.steps.pop(index)
            self.refresh_tree(select=min(index, len(self.steps) - 1))

    def move_selected(self, direction):
        index = self.selected_index()
        if index is None:
            return
        target = index + direction
        if 0 <= target < len(self.steps):
            self.steps[index], self.steps[target] = self.steps[target], self.steps[index]
            self.refresh_tree(select=target)

    def clear_steps(self):
        if self.steps and messagebox.askyesno("Clear sequence", "Remove every click from the current sequence?"):
            self.steps.clear(); self.refresh_tree()

    def _document(self):
        return {"app": APP_NAME, "version": 1, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "settings": {"start_delay": self.start_delay_var.get(), "repeat": self.repeat_var.get()},
                "steps": [asdict(step) for step in self.steps]}

    def _apply_document(self, data):
        raw_steps = data.get("steps", data) if isinstance(data, dict) else data
        loaded = [ClickStep(int(item["x"]), int(item["y"]), max(0, int(item["delay_ms"]))) for item in raw_steps]
        self.steps = loaded
        if isinstance(data, dict):
            settings = data.get("settings", {})
            self.start_delay_var.set(str(settings.get("start_delay", self.start_delay_var.get())))
            self.repeat_var.set(str(settings.get("repeat", self.repeat_var.get())))
        self.refresh_tree(select=0 if loaded else None)

    @property
    def data_folder(self):
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AutoClicker"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            folder = Path(tempfile.gettempdir()) / "AutoClicker"
            folder.mkdir(parents=True, exist_ok=True)
        return folder

    @property
    def profiles_folder(self):
        folder = self.data_folder / "profiles"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _profile_entries(self):
        entries = []
        for path in self.profiles_folder.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entries.append((str(data.get("profile_name", path.stem)), path))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return sorted(entries, key=lambda item: item[0].casefold())

    def _refresh_profiles(self, select_name=None):
        entries = self._profile_entries()
        self.profile_paths = {name: path for name, path in entries}
        names = [name for name, _ in entries]
        self.profile_combo["values"] = names
        if select_name in names:
            self.profile_var.set(select_name)
        elif self.profile_var.get() not in names:
            self.profile_var.set(names[0] if names else "")

    def save_profile_as(self):
        name = simpledialog.askstring("Save profile", "Profile name:", parent=self.root)
        if not name or not name.strip():
            return
        name = name.strip()
        existing = self.profile_paths.get(name)
        if existing and not messagebox.askyesno("Replace profile", f'Replace the existing profile "{name}"?'):
            return
        safe_name = re.sub(r'[<>:"/\\|?*]+', "_", name).strip(" .") or "profile"
        path = existing or (self.profiles_folder / f"{safe_name}.json")
        data = self._document()
        data["profile_name"] = name
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._refresh_profiles(name)
            self.set_status("●  PROFILE SAVED", self.GREEN)
        except OSError as exc:
            messagebox.showerror("Profile save failed", str(exc))

    def load_selected_profile(self):
        name = self.profile_var.get()
        path = self.profile_paths.get(name)
        if not path:
            messagebox.showinfo("No profile selected", "Save or select a profile first.")
            return
        try:
            self._apply_document(json.loads(path.read_text(encoding="utf-8")))
            self.set_status("●  PROFILE LOADED", self.BLUE)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            messagebox.showerror("Profile load failed", str(exc))

    def delete_profile(self):
        name = self.profile_var.get()
        path = self.profile_paths.get(name)
        if not path:
            return
        if not messagebox.askyesno("Delete profile", f'Delete the profile "{name}"?'):
            return
        try:
            path.unlink()
            self._refresh_profiles()
            self.set_status("●  PROFILE DELETED", self.RED)
        except OSError as exc:
            messagebox.showerror("Profile delete failed", str(exc))

    def save_file(self):
        path = filedialog.asksaveasfilename(title="Export click sequence", defaultextension=".json",
                                            filetypes=[("Auto Clicker profile", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(self._document(), ensure_ascii=False, indent=2), encoding="utf-8")
            self.set_status("●  EXPORTED", self.GREEN)
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def load_file(self):
        path = filedialog.askopenfilename(title="Import click sequence",
                                          filetypes=[("Auto Clicker profile", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self._apply_document(data)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            messagebox.showerror("Import failed", f"This is not a valid Auto Clicker profile.\n\n{exc}")
            return
        self.set_status("●  IMPORTED", self.BLUE)

    @property
    def autosave_path(self):
        return self.data_folder / "last-session.json"

    def _autosave(self):
        try:
            self.autosave_path.write_text(json.dumps(self._document(), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load_autosave(self):
        try:
            if self.autosave_path.exists():
                data = json.loads(self.autosave_path.read_text(encoding="utf-8"))
                self._apply_document(data)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass

    def set_status(self, text, color):
        self.status_badge.config(text=text, fg=color)

    def on_close(self):
        self.stop_event.set()
        self.recording = False
        self.recorder.stop()
        self._autosave()
        self.root.destroy()


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("Auto Clicker currently supports Windows only.")
    root = tk.Tk()
    AutoClickerApp(root)
    root.mainloop()

