"""PairWatch desktop app: start window -> camera check & calibration -> coding window -> report."""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path

if sys.stdout is None:  # windowed .exe has no console
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import tkinter as tk  # noqa: E402
from tkinter import messagebox, ttk  # noqa: E402

from .cpp import find_gxx, run_tests  # noqa: E402
from .report import CREDIT, class_report, pair_report  # noqa: E402
from .session import Session, data_root, open_folder, sessions_root  # noqa: E402
from .tasks import load_tasks  # noqa: E402

APP = "PairWatch"
BLUE, ORANGE, GREEN, RED = "#2f6db5", "#e07b39", "#2e7d32", "#c62828"
SIDE_NAME = {"L": "LEFT student", "R": "RIGHT student"}
SIDE_COLOUR = {"L": BLUE, "R": ORANGE}
KEYWORDS = r"\b(int|long|double|float|char|bool|void|string|vector|stack|queue|map|set|auto|const|return|if|else|for|while|do|break|continue|include|using|namespace|std|cin|cout|endl|true|false|struct|class|public|private|switch|case|default)\b"
IGNORED_KEYS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Caps_Lock", "Win_L", "Win_R",
                "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next", "F2", "F5", "Escape"}


def resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parents[1] / "packaging"))
    p = Path(base) / name
    return str(p) if p.exists() else ""


def screenshot(win, path: Path):
    try:
        from PIL import ImageGrab
        win.update()
        x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
        ImageGrab.grab(bbox=(x - 8, y - 32, x + w + 8, y + h + 8)).save(path)
    except Exception:
        pass


class CodingWindow(tk.Toplevel):
    def __init__(self, master, session: Session, sensor, on_close, gxx: str | None):
        super().__init__(master)
        self.session, self.sensor, self.on_close_cb, self.gxx = session, sensor, on_close, gxx
        self.title(f"{APP} – {session.pair}")
        self.geometry("1280x780")
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.tasks = load_tasks(data_root() / "tasks.json")
        self.code = {t.id: t.starter for t in self.tasks}
        self.solved: set[str] = set()
        self.runs = 0
        self.current = None
        self.t_start = time.time()
        self._build()
        self.select_task(0)
        self.protocol("WM_DELETE_WINDOW", self.end_session)
        self.after(500, self._tick)

    # ---------------------------------------------------------------- layout
    def _build(self):
        top = tk.Frame(self, bg="#20242b")
        top.pack(fill="x")
        tk.Label(top, text=f"  {APP}  ·  {self.session.pair}", fg="white", bg="#20242b", font=("Segoe UI", 13, "bold")).pack(side="left", pady=8)
        self.timer = tk.Label(top, text="00:00", fg="#ddd", bg="#20242b", font=("Consolas", 13))
        self.timer.pack(side="left", padx=18)
        tk.Button(top, text="End session", command=self.end_session, bg="#444", fg="white", relief="flat", padx=12).pack(side="right", padx=10)
        self.sensor_lbl = tk.Label(top, text="", fg="#bbb", bg="#20242b", font=("Segoe UI", 10))
        self.sensor_lbl.pack(side="right", padx=10)
        self.switch_btn = tk.Button(top, text="Switch driver  (F2)", command=self.switch_driver, relief="flat", padx=10)
        self.switch_btn.pack(side="right", padx=6)
        self.driver_lbl = tk.Label(top, text="", fg="white", font=("Segoe UI", 12, "bold"), padx=14, pady=4)
        self.driver_lbl.pack(side="right", padx=6)

        body = tk.PanedWindow(self, orient="horizontal", sashwidth=5)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, width=380)
        body.add(left, minsize=300)
        tk.Label(left, text="Tasks", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.task_list = tk.Listbox(left, height=len(self.tasks), font=("Segoe UI", 10), activestyle="none", exportselection=False)
        self.task_list.pack(fill="x", padx=8)
        self.task_list.bind("<<ListboxSelect>>", lambda e: self.select_task(self.task_list.curselection()[0]) if self.task_list.curselection() else None)
        self.desc = tk.Text(left, wrap="word", height=12, font=("Segoe UI", 10), relief="flat", bg="#f6f7f9", padx=8, pady=6)
        self.desc.pack(fill="x", padx=8, pady=8)
        tk.Label(left, text="Test results", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8)
        self.results = tk.Text(left, wrap="word", font=("Consolas", 9), relief="flat", bg="#f6f7f9", padx=8, pady=6)
        tk.Label(left, text=CREDIT, fg=BLUE, font=("Segoe UI", 9, "italic"), wraplength=360,
                 justify="left").pack(side="bottom", anchor="w", padx=8, pady=(0, 8))  # pinned, never squeezed out
        self.results.pack(fill="both", expand=True, padx=8, pady=(2, 4))
        self.results.tag_config("ok", foreground=GREEN)
        self.results.tag_config("bad", foreground=RED)

        right = tk.Frame(body)
        body.add(right, minsize=500)
        ed = tk.Frame(right)
        ed.pack(fill="both", expand=True, padx=(0, 8), pady=8)
        self.lines = tk.Text(ed, width=4, font=("Consolas", 12), bg="#eef0f3", fg="#888", relief="flat", state="disabled", padx=4)
        self.lines.pack(side="left", fill="y")
        self.editor = tk.Text(ed, font=("Consolas", 12), undo=True, wrap="none", relief="flat", padx=8, pady=4,
                              insertwidth=3, tabs=("1c",))
        self.editor.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(ed, command=self._scroll)
        sb.pack(side="right", fill="y")
        self.editor.config(yscrollcommand=lambda a, b: (sb.set(a, b), self.lines.yview_moveto(a)))
        self.editor.tag_config("kw", foreground="#1f4fb5")
        self.editor.tag_config("str", foreground="#a3412a")
        self.editor.tag_config("com", foreground="#6a8a5a")
        self.editor.bind("<KeyPress>", self._on_key)
        self.editor.bind("<KeyRelease>", lambda e: self._refresh_editor())
        self.editor.bind("<Return>", self._newline)
        self.editor.bind("<Tab>", lambda e: (self.editor.insert("insert", "    "), "break")[1])

        bottom = tk.Frame(right)
        bottom.pack(fill="x", padx=(0, 8), pady=(0, 10))
        self.run_btn = tk.Button(bottom, text="Run tests  (F5)", command=self.run_tests, bg=GREEN, fg="white",
                                 font=("Segoe UI", 11, "bold"), relief="flat", padx=16, pady=4)
        self.run_btn.pack(side="left")
        tk.Button(bottom, text="Next task", command=lambda: self.select_task(min(self.current + 1, len(self.tasks) - 1)),
                  relief="flat", padx=12).pack(side="left", padx=8)
        tk.Button(bottom, text="Reset code", command=self.reset_code, relief="flat", padx=12).pack(side="left")
        self.bind("<F2>", lambda e: self.switch_driver())
        self.bind("<F5>", lambda e: self.run_tests())
        self._show_driver()

    def _scroll(self, *a):
        self.editor.yview(*a)
        self.lines.yview(*a)

    # ---------------------------------------------------------------- editor
    def _on_key(self, e):
        if e.keysym not in IGNORED_KEYS and not (e.state & 0x4 and e.keysym.lower() in ("c", "a")):
            self.session.event("key")

    def _newline(self, e):
        line = self.editor.get("insert linestart", "insert")
        indent = re.match(r"\s*", line).group(0)
        if line.rstrip().endswith("{"):
            indent += "    "
        self.editor.insert("insert", "\n" + indent)
        self.editor.see("insert")
        self._refresh_editor()
        return "break"

    def _refresh_editor(self):
        n = int(self.editor.index("end-1c").split(".")[0])
        self.lines.config(state="normal")
        self.lines.delete("1.0", "end")
        self.lines.insert("1.0", "\n".join(str(i) for i in range(1, n + 1)))
        self.lines.config(state="disabled")
        self.lines.yview_moveto(self.editor.yview()[0])
        text = self.editor.get("1.0", "end-1c")
        for tag in ("kw", "str", "com"):
            self.editor.tag_remove(tag, "1.0", "end")
        for tag, pat in (("kw", KEYWORDS), ("str", r'"[^"\n]*"'), ("com", r"//[^\n]*")):
            for m in re.finditer(pat, text):
                self.editor.tag_add(tag, f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    # ---------------------------------------------------------------- tasks
    def _task_label(self, i):
        t = self.tasks[i]
        return f"{'✔ ' if t.id in self.solved else '   '}{i + 1}. {t.title}  " + "•" * t.level

    def select_task(self, i: int):
        if self.current is not None:
            self.code[self.tasks[self.current].id] = self.editor.get("1.0", "end-1c")
        self.current = i
        t = self.tasks[i]
        self.task_list.delete(0, "end")
        for k in range(len(self.tasks)):
            self.task_list.insert("end", self._task_label(k))
        self.task_list.selection_set(i)
        self.desc.config(state="normal")
        self.desc.delete("1.0", "end")
        self.desc.insert("1.0", f"{t.title}\n\n{t.text}")
        self.desc.tag_add("h", "1.0", "1.end")
        self.desc.tag_config("h", font=("Segoe UI", 12, "bold"))
        self.desc.config(state="disabled")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.code[t.id])
        self.editor.edit_reset()
        self._refresh_editor()
        self.results.delete("1.0", "end")
        if self.session.task != t.id:
            self.session.task = t.id
            self.session.event("task_start")

    def reset_code(self):
        t = self.tasks[self.current]
        if messagebox.askyesno(APP, "Replace your code with the empty starter code?", parent=self):
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", t.starter)
            self._refresh_editor()

    def run_tests(self, wait: bool = False):
        if str(self.run_btn["state"]) == "disabled":
            return
        t = self.tasks[self.current]
        code = self.editor.get("1.0", "end-1c")
        self.code[t.id] = code
        self.runs += 1
        self.session.save_code(code, self.runs)
        self.run_btn.config(state="disabled", text="Running…")
        self.results.delete("1.0", "end")
        self.results.insert("end", "Compiling and testing…\n")
        out = {}

        def work():
            out["r"] = run_tests(code, t.tests, self.gxx)

        th = threading.Thread(target=work, daemon=True)
        th.start()
        if wait:
            th.join()
            self._show_results(t, out["r"])
        else:
            def poll():
                if th.is_alive():
                    self.after(100, poll)
                else:
                    self._show_results(t, out["r"])
            poll()

    def _show_results(self, t, r):
        self.run_btn.config(state="normal", text="Run tests  (F5)")
        self.session.event("run", {"compiled": r.compiled, "passed": r.passed, "of": len(t.tests), "solved": r.solved})
        self.results.delete("1.0", "end")
        if not r.compiled:
            self.results.insert("end", "Did not compile:\n\n", "bad")
            self.results.insert("end", r.compile_output)
            return
        for k, tr in enumerate(r.tests, 1):
            tag = "ok" if tr.passed else "bad"
            self.results.insert("end", f"Test {k}: {'passed' if tr.passed else 'FAILED'}\n", tag)
            if not tr.passed:
                self.results.insert("end", f"  input:    {tr.stdin.strip()[:120]}\n  expected: {tr.expected}\n  got:      {tr.got[:200] or '(nothing)'}\n")
                if tr.note:
                    self.results.insert("end", f"  note:     {tr.note}\n")
        if r.solved:
            self.solved.add(t.id)
            self.results.insert("end", f"\nAll {len(r.tests)} tests passed. Well done! Press 'Next task'.\n", "ok")
            self.task_list.delete(self.current)
            self.task_list.insert(self.current, self._task_label(self.current))
            self.task_list.selection_set(self.current)
        else:
            self.results.insert("end", f"\n{r.passed} of {len(r.tests)} tests passed.\n")

    # ---------------------------------------------------------------- roles & status
    def switch_driver(self):
        self.session.driver = "R" if self.session.driver == "L" else "L"
        self.session.event("driver")
        self._show_driver()

    def _show_driver(self):
        d = self.session.driver
        self.driver_lbl.config(text=f"Driver: {SIDE_NAME[d]}", bg=SIDE_COLOUR[d])

    def _tick(self):
        if not self.winfo_exists():
            return
        el = int(time.time() - self.t_start)
        self.timer.config(text=f"{el // 60:02d}:{el % 60:02d}")
        if self.sensor is not None:
            s = self.sensor.status
            who = {"L": "left", "R": "right", "both": "both", "?": "someone"}.get(s["speaker"], "–")
            self.sensor_lbl.config(text=f"Faces {s['faces']}/2   ·   Mic {'on' if s['mic'] else 'off'}   ·   Speaking: {who}")
        self.after(500, self._tick)

    def end_session(self, ask: bool = True):
        if ask and not messagebox.askyesno(APP, "End this session and create the report?", parent=self):
            return
        if self.sensor is not None:
            self.sensor.stop()
            self.sensor.join(timeout=3)
        self.session.close()
        report = pair_report(self.session.dir)
        self.destroy()
        self.on_close_cb(report)


class CalibrationWindow(tk.Toplevel):
    """Shows the camera view (faces blurred), then three dots for both students to look at."""
    STEPS = (("middle", 0.5, "Both: look at the MIDDLE of the screen"),
             ("top", 0.1, "Both: look at the TOP of the screen"),
             ("bottom", 0.9, "Both: look at the BOTTOM of the screen"))

    def __init__(self, master, sensor, on_done):
        super().__init__(master)
        self.sensor, self.on_done = sensor, on_done
        self.title(f"{APP} – camera check")
        self.geometry("1100x760")
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.configure(bg="white")
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        bar = tk.Frame(self, bg="white")
        bar.pack(fill="x", pady=10)
        self.msg = tk.Label(bar, text="Sit side by side, both facing the screen. Check that the camera finds both faces. (The view is pixelated on purpose.)",
                            bg="white", font=("Segoe UI", 12))
        self.msg.pack()
        btns = tk.Frame(bar, bg="white")
        btns.pack(pady=6)
        self.go = tk.Button(btns, text="Start calibration (10 seconds)", command=self.calibrate, bg=BLUE, fg="white",
                            font=("Segoe UI", 11, "bold"), relief="flat", padx=14, pady=4)
        self.go.pack(side="left", padx=6)
        tk.Button(btns, text="Skip", command=self.finish, relief="flat", padx=12).pack(side="left", padx=6)
        self.photo = None
        self.step = -1
        sensor.want_preview = True
        self.protocol("WM_DELETE_WINDOW", self.finish)
        self.after(200, self._preview)

    def _preview(self):
        if not self.winfo_exists():
            return
        self.canvas.delete("all")
        w, h = max(self.canvas.winfo_width(), 400), max(self.canvas.winfo_height(), 300)
        if self.step < 0:
            img = self.sensor.preview
            if img is not None:
                try:
                    from PIL import Image, ImageTk
                    rgb = img[:, :, ::-1]
                    pil = Image.fromarray(rgb)
                    scale = min(w / pil.width, h / pil.height, 1.6)
                    pil = pil.resize((int(pil.width * scale), int(pil.height * scale)))
                    self.photo = ImageTk.PhotoImage(pil)
                    self.canvas.create_image(w // 2, h // 2, image=self.photo)
                except Exception:
                    pass
            n = self.sensor.status["faces"]
            colour = GREEN if n == 2 else RED
            self.canvas.create_text(w // 2, 28, text=f"Faces found: {n} of 2", fill=colour, font=("Segoe UI", 16, "bold"))
            if self.sensor.status.get("error"):
                self.canvas.create_text(w // 2, h - 20, text=self.sensor.status["error"], fill="#888", font=("Segoe UI", 9))
        else:
            target, y, text = self.STEPS[self.step]
            self.canvas.create_oval(w // 2 - 22, int(y * h) - 22, w // 2 + 22, int(y * h) + 22, fill=RED, outline="")
            self.canvas.create_text(w // 2, h // 2 + (60 if target == "middle" else 0), text=text, font=("Segoe UI", 18, "bold"))
        self.after(100, self._preview)

    def calibrate(self):
        self.go.config(state="disabled")
        self.sensor.want_preview = False
        self.step = 0
        self.msg.config(text="Keep your heads still and move only your eyes and head slightly toward the red dot.")
        self._run_step()

    def _run_step(self):
        if self.step >= len(self.STEPS):
            self.sensor.calib_target = None
            return self.finish()
        self.sensor.calib_target = None
        self.after(900, lambda: setattr(self.sensor, "calib_target", self.STEPS[self.step][0]))
        def nxt():
            self.step += 1
            self._run_step()
        self.after(3300, nxt)

    def finish(self):
        if getattr(self, "_done", False):
            return
        self._done = True
        self.sensor.calib_target = None
        self.sensor.want_preview = False
        if self.winfo_exists():
            self.destroy()
        self.on_done()


class ConditionWindow(tk.Toplevel):
    """Condition test: one volunteer follows prompts; the teacher records the conditions."""

    def __init__(self, master, image_source: str | None = None, root_dir: Path | None = None,
                 hold: float = 3.0, settle: float = 1.0, on_close=None):
        from .conditions import CONDITIONS, tests_root
        super().__init__(master)
        self.title(f"{APP} – condition test")
        self.geometry("1280x780")
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.image_source, self.hold, self.settle, self.on_close_cb = image_source, hold, settle, on_close
        self.root_dir = root_dir or tests_root()
        self.recorder = None
        self.photo = None
        self.mode = "preview"          # preview | countdown | prompt | done
        self.prompt_target = None
        self.countdown = 0
        self.last_result = None

        left = tk.Frame(self, width=380, padx=14, pady=12)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="Condition test", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(left, justify="left", wraplength=350, fg="#555", text=(
            "When does webcam attention sensing work? One volunteer sits in front of the camera. "
            "Choose the conditions that are true right now, then press Run trial (about 30 seconds). "
            "The volunteer follows the prompts on the screen. Repeat with the same volunteer under "
            "other conditions.")).pack(anchor="w", pady=(4, 10))
        row = tk.Frame(left)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Volunteer code", width=14, anchor="w").pack(side="left")
        self.code = tk.Entry(row, width=22)
        self.code.insert(0, "V01")
        self.code.pack(side="left")
        self.combos = {}
        for factor, options in CONDITIONS.items():
            row = tk.Frame(left)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=factor.replace("_", " ").capitalize(), width=14, anchor="w").pack(side="left")
            cb = ttk.Combobox(row, state="readonly", width=22, values=options)
            cb.current(0)
            cb.pack(side="left")
            self.combos[factor] = cb
        row = tk.Frame(left)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Camera index", width=14, anchor="w").pack(side="left")
        self.cam = ttk.Combobox(row, state="readonly", width=22, values=["0", "1", "2"])
        self.cam.current(0)
        self.cam.pack(side="left")
        self.cam.bind("<<ComboboxSelected>>", lambda e: self._start_recorder())
        self.run_btn = tk.Button(left, text="Run trial  (≈30 s)", command=self.run_trial, bg=BLUE, fg="white",
                                 font=("Segoe UI", 12, "bold"), relief="flat", padx=14, pady=5)
        self.run_btn.pack(anchor="w", pady=(14, 6))
        b = tk.Frame(left)
        b.pack(anchor="w")
        tk.Button(b, text="Condition report", command=self.report, relief="flat", padx=10).pack(side="left")
        tk.Button(b, text="Folder", command=lambda: open_folder(self.root_dir), relief="flat", padx=10).pack(side="left", padx=6)
        self.status = tk.Label(left, text="", justify="left", wraplength=350, font=("Segoe UI", 10))
        self.status.pack(anchor="w", pady=10)
        tk.Label(left, text="Only numbers are saved: face found, head direction, face size and\n"
                            "picture brightness. No images.", fg=GREEN, justify="left").pack(anchor="w")
        tk.Label(left, text=CREDIT, fg=BLUE, font=("Segoe UI", 9, "italic"), wraplength=350,
                 justify="left").pack(side="bottom", anchor="w")
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._start_recorder()
        self.after(150, self._draw)

    def _start_recorder(self):
        from .conditions import TrialRecorder
        if self.recorder is not None:
            self.recorder.stop()
        self.recorder = TrialRecorder(camera=int(self.cam.get()), image_source=self.image_source)
        self.recorder.settle = self.settle
        self.recorder.start()

    def _draw(self):
        if not self.winfo_exists():
            return
        from .conditions import PROMPTS
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 500), max(c.winfo_height(), 400)
        if self.mode in ("preview", "done"):
            img = self.recorder.preview if self.recorder else None
            if img is not None:
                try:
                    from PIL import Image, ImageTk
                    pil = Image.fromarray(img[:, :, ::-1])
                    sc = min(w * 0.8 / pil.width, h * 0.6 / pil.height, 1.8)
                    self.photo = ImageTk.PhotoImage(pil.resize((int(pil.width * sc), int(pil.height * sc))))
                    c.create_image(w // 2, h // 2, image=self.photo)
                except Exception:
                    pass
            found = self.recorder is not None and self.recorder.latest is not None
            c.create_text(w // 2, 34, text="Face found" if found else "No face found",
                          fill=GREEN if found else RED, font=("Segoe UI", 18, "bold"))
            c.create_text(w // 2, h - 30, text="View pixelated on purpose. Sit as you normally would.",
                          fill="#888", font=("Segoe UI", 10))
            if self.recorder is not None and self.recorder.error:
                c.create_text(w // 2, h - 54, text=self.recorder.error, fill=RED, font=("Segoe UI", 10))
        elif self.mode == "countdown":
            c.create_text(w // 2, h // 2, text=str(self.countdown), font=("Segoe UI", 96, "bold"), fill=BLUE)
            c.create_text(w // 2, h // 2 + 110, text="Get ready: follow the red dot and the instructions",
                          font=("Segoe UI", 16))
        elif self.mode == "prompt":
            t = self.prompt_target
            r = 26
            if t in ("top", "middle", "bottom"):
                y = {"top": 0.08, "middle": 0.5, "bottom": 0.92}[t] * h
                c.create_oval(w // 2 - r, y - r, w // 2 + r, y + r, fill=RED, outline="")
            elif t == "left":
                c.create_polygon(40, h // 2, 160, h // 2 - 70, 160, h // 2 + 70, fill=RED)
            elif t == "right":
                c.create_polygon(w - 40, h // 2, w - 160, h // 2 - 70, w - 160, h // 2 + 70, fill=RED)
            elif t == "down":
                c.create_polygon(w // 2, h - 30, w // 2 - 70, h - 150, w // 2 + 70, h - 150, fill=RED)
            ty = h // 2 + 70 if t != "middle" else h // 2 + 90
            c.create_text(w // 2, ty, text=PROMPTS[t], font=("Segoe UI", 18, "bold"), width=w - 340)
        self.after(100, self._draw)

    def conditions(self) -> dict:
        return {k: cb.get() for k, cb in self.combos.items()}

    def run_trial(self, done_cb=None):
        from .conditions import trial_plan
        self.run_btn.config(state="disabled")
        self.recorder.frames = []
        plan = trial_plan(hold=self.hold)
        self.mode, self.countdown = "countdown", 3

        def count():
            if self.countdown > 1:
                self.countdown -= 1
                self.after(700 if self.hold < 1 else 1000, count)
            else:
                self.recorder.recording = True
                step(0)

        def step(i):
            if i >= len(plan):
                return finish()
            st = plan[i]
            self.mode, self.prompt_target = "prompt", st.target
            self.recorder.begin(st.phase, st.target)
            self.after(int(st.seconds * 1000), lambda: step(i + 1))

        def finish():
            from .conditions import save_trial
            self.recorder.recording = False
            frames = list(self.recorder.frames)
            d = save_trial(self.root_dir, self.code.get().strip() or "V", self.conditions(), frames)
            r = json.loads((d / "trial.json").read_text(encoding="utf-8"))["result"]
            self.last_result = r
            self.mode = "done"
            self.run_btn.config(state="normal")
            if not r.get("test_frames"):
                self.status.config(text="No frames were recorded. Check the camera.", fg=RED)
            else:
                ok = r["face_found"] >= 0.9 and r["accuracy_all_frames"] >= 0.7
                self.status.config(fg=GREEN if ok else RED, text=(
                    f"Trial saved.\nFace found: {100 * r['face_found']:.0f}% of the time\n"
                    f"Direction correct: {100 * r['accuracy_all_frames']:.0f}%"
                    + ("" if r["calibrated"] else "\n(calibration incomplete: the face was missing during the first part)")))
            if done_cb:
                done_cb(d)

        self.after(700 if self.hold < 1 else 1000, count)

    def report(self):
        from .conditions import condition_report
        out = condition_report(self.root_dir)
        if out:
            webbrowser.open(out.as_uri())
        else:
            messagebox.showinfo(APP, "No trials yet.", parent=self)

    def close(self):
        if self.recorder is not None:
            self.recorder.stop()
        self.destroy()
        if self.on_close_cb:
            self.on_close_cb()


class StartWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP)
        root.resizable(False, False)
        ico = resource("pairwatch.ico")
        if ico:
            try:
                root.iconbitmap(default=ico)  # also used by every other PairWatch window
            except tk.TclError:
                pass
        self.gxx = find_gxx()
        pad = {"padx": 14, "pady": 4}
        tk.Label(root, text="PairWatch", font=("Segoe UI", 20, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 0))
        tk.Label(root, text="Pair programming in C++: how two students work together at one screen.", fg="#555").grid(row=1, column=0, columnspan=2, sticky="w", padx=14)
        tk.Label(root, text="Pair name").grid(row=2, column=0, sticky="w", **pad)
        self.pair = tk.Entry(root, width=30)
        n = len([p for p in sessions_root().iterdir() if p.is_dir()]) + 1
        self.pair.insert(0, f"Pair {n}")
        self.pair.grid(row=2, column=1, sticky="w", **pad)
        tk.Label(root, text="Camera").grid(row=3, column=0, sticky="w", **pad)
        self.cam = ttk.Combobox(root, state="readonly", width=27, values=["Laptop camera (0)", "USB / second camera (1)", "Third camera (2)"])
        self.cam.current(0)
        self.cam.grid(row=3, column=1, sticky="w", **pad)
        self.consent = tk.BooleanVar(value=False)
        tk.Checkbutton(root, text="Both students know about the camera and microphone and agreed.\nNo video or audio is saved, only numbers.",
                       variable=self.consent, justify="left").grid(row=4, column=0, columnspan=2, sticky="w", padx=14, pady=(8, 4))
        comp = f"C++ compiler: ready" if self.gxx else "C++ compiler: NOT FOUND (install MinGW or Dev-C++)"
        tk.Label(root, text=comp, fg=GREEN if self.gxx else RED).grid(row=5, column=0, columnspan=2, sticky="w", **pad)
        b = tk.Frame(root)
        b.grid(row=6, column=0, columnspan=2, pady=10)
        self.start_btn = tk.Button(b, text="Start session", command=self.start, bg=BLUE, fg="white", font=("Segoe UI", 12, "bold"),
                                   relief="flat", padx=16, pady=5)
        self.start_btn.pack(side="left", padx=6)
        tk.Button(b, text="Class report", command=self.class_report, relief="flat", padx=12, pady=5).pack(side="left", padx=4)
        tk.Button(b, text="Condition test", command=self.condition_test, relief="flat", padx=12, pady=5).pack(side="left", padx=4)
        tk.Button(b, text="Data folder", command=lambda: open_folder(data_root()), relief="flat", padx=12, pady=5).pack(side="left", padx=4)
        self.status = tk.Label(root, text="", fg="#555")
        self.status.grid(row=7, column=0, columnspan=2, sticky="w", padx=14)
        tk.Label(root, text=CREDIT, fg=BLUE, font=("Segoe UI", 9, "italic")).grid(row=8, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 10))
        self.sensor = None
        self.session = None

    def camera_index(self) -> int:
        c = self.cam.get()
        return int(c[c.rfind("(") + 1:c.rfind(")")])

    def start(self, camera: int | None = None, image_source: str | None = None, root: Path | None = None,
              skip_calibration: bool = False):
        if not self.consent.get():
            messagebox.showinfo(APP, "Please tick the consent box first.")
            return
        name = self.pair.get().strip() or "Pair"
        from .sensing import SensorThread
        self.session = Session(name, root=root, meta={"camera": camera if camera is not None else self.camera_index()})
        self.sensor = SensorThread(self.session.feature, camera=camera if camera is not None else self.camera_index(),
                                   image_source=image_source)
        self.sensor.start()
        self.root.withdraw()
        if skip_calibration:
            self.open_coding()
        else:
            self.calib_window = CalibrationWindow(self.root, self.sensor, self.open_coding)

    def open_coding(self):
        self.session.event("calibrated", {s: c.ready for s, c in self.sensor.calib.items()})
        self.coding = CodingWindow(self.root, self.session, self.sensor, self.finished, self.gxx)

    def finished(self, report: Path):
        self.root.deiconify()
        self.status.config(text=f"Report saved: {report}")
        n = len([p for p in sessions_root().iterdir() if p.is_dir()]) + 1
        self.pair.delete(0, "end")
        self.pair.insert(0, f"Pair {n}")
        self.consent.set(False)
        webbrowser.open(report.as_uri())

    def condition_test(self):
        self.root.withdraw()
        ConditionWindow(self.root, on_close=self.root.deiconify)

    def class_report(self):
        out = class_report(sessions_root())
        if out:
            webbrowser.open(out.as_uri())
        else:
            messagebox.showinfo(APP, "No sessions yet.")


def selftest(out_dir: Path, image: str | None):
    """Automatic check used by the Windows build: runs a whole session without a person."""
    from .tasks import TASKS
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"compiler": None, "solved": False, "report": False, "class_report": False, "feature_rows": 0, "faces_seen": 0}
    root = tk.Tk()
    app = StartWindow(root)
    result["compiler"] = app.gxx
    root.update()
    screenshot(root, out_dir / "start_window.png")
    app.consent.set(True)
    sroot = out_dir / "sessions"
    sroot.mkdir(exist_ok=True)

    def step_calibration():
        app.start(camera=99, image_source=image, root=sroot)
        root.after(3500, lambda: (screenshot(app.calib_window, out_dir / "camera_check.png"), app.calib_window.finish(),
                                  root.after(1500, step_coding)))

    def step_coding():
        cw = app.coding
        cw.editor.delete("1.0", "end")
        cw.editor.insert("1.0", "#include <iostream>\nusing namespace std;\n\nint main() {\n    \n    return 0;\n}\n")
        cw._refresh_editor()
        cw.run_tests(wait=True)          # starter code: should fail the tests
        for _ in range(40):
            app.session.event("key")
        cw.switch_driver()
        cw.editor.delete("1.0", "end")
        cw.editor.insert("1.0", TASKS[0].solution)
        cw._refresh_editor()
        cw.run_tests(wait=True)          # reference solution: should pass
        result["solved"] = TASKS[0].id in cw.solved
        cw.update()
        screenshot(cw, out_dir / "coding_window.png")
        result["faces_seen"] = app.sensor.status["faces"]
        root.after(800, lambda: finish(cw))

    def finish(cw):
        cw.end_session(ask=False)

    orig_finished = app.finished
    def finished(report):
        result["report"] = report.exists()
        result["feature_rows"] = sum(1 for _ in open(app.session.dir / "features.csv")) - 1
        result["class_report"] = bool(class_report(sroot, out_dir / "class_report.html"))
        (out_dir / "pair_report.html").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
        root.after(300, root.destroy)
    app.finished = finished
    root.after(800, step_calibration)
    root.mainloop()
    (out_dir / "selftest.json").write_text(json.dumps(result, indent=1))
    ok = bool(result["compiler"]) and result["solved"] and result["report"] and result["class_report"]
    return 0 if ok else 1


def selftest_conditions(out_dir: Path, image: str | None):
    """Automatic check of the condition test (used by the Windows build)."""
    from .conditions import condition_report
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"trial_saved": False, "test_frames": 0, "face_found": None, "report": False}
    root = tk.Tk()
    root.withdraw()
    win = ConditionWindow(root, image_source=image, root_dir=out_dir / "condition_tests", hold=1.0, settle=0.3)
    win.combos["light"].set("dim")

    def start():
        screenshot(win, out_dir / "condition_window.png")
        win.run_trial(done_cb=done)
        root.after(9000, lambda: screenshot(win, out_dir / "condition_prompt.png"))

    def done(d):
        r = json.loads((d / "trial.json").read_text(encoding="utf-8"))["result"]
        result.update(trial_saved=True, test_frames=r.get("test_frames", 0), face_found=r.get("face_found"),
                      accuracy=r.get("accuracy_all_frames"), calibrated=r.get("calibrated"))
        rep = condition_report(out_dir / "condition_tests", out_dir / "condition_report.html")
        result["report"] = bool(rep and rep.exists())
        root.after(1200, lambda: (screenshot(win, out_dir / "condition_result.png"), win.close(), root.destroy()))

    root.after(4000, start)
    root.after(60000, root.destroy)  # safety net
    root.mainloop()
    (out_dir / "selftest_conditions.json").write_text(json.dumps(result, indent=1))
    return 0 if result["trial_saved"] and result["test_frames"] > 0 and result["report"] else 1


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    args = sys.argv[1:]
    if args[:1] == ["--selftest-conditions"]:
        out = Path(args[1]) if len(args) > 1 else Path.cwd() / "selftest"
        image = args[args.index("--image") + 1] if "--image" in args else None
        sys.exit(selftest_conditions(out, image))
    if args[:1] == ["--selftest"]:
        out = Path(args[1]) if len(args) > 1 else Path.cwd() / "selftest"
        image = args[args.index("--image") + 1] if "--image" in args else None
        sys.exit(selftest(out, image))
    root = tk.Tk()
    StartWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
