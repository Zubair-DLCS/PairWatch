"""One pair-programming session on disk: numbers only (no video, no audio).

Documents/PairWatch/sessions/<date>_<pair>/
    features.csv   5 rows per second: faces, head direction, where each student looks, speech, speaker
    events.csv     task start, key presses (who was driver, not which key), test runs, driver switches
    code/          the pair's code at each test run
    summary.json   all metrics (see metrics.py)
    report.html    the pair report
"""
from __future__ import annotations

import csv
import json
import re
import sys
import threading
import time
from pathlib import Path

FEATURE_COLS = ["t", "face_L", "face_R", "look_L", "look_R", "yaw_L", "pitch_L", "yaw_R", "pitch_R",
                "mouth_L", "mouth_R", "speech", "level", "speaker"]
EVENT_COLS = ["t", "type", "driver", "task", "detail"]


def data_root() -> Path:
    base = Path.home() / "Documents" / "PairWatch"
    base.mkdir(parents=True, exist_ok=True)
    return base


def sessions_root() -> Path:
    p = data_root() / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s.strip())[:40] or "pair"


class Session:
    def __init__(self, pair: str, root: Path | None = None, meta: dict | None = None, start_t: float | None = None):
        self.pair = pair
        stamp = time.strftime('%Y-%m-%d_%H%M%S', time.localtime(start_t or time.time()))
        self.dir = (root or sessions_root()) / f"{stamp}_{safe_name(pair)}"
        (self.dir / "code").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ff = open(self.dir / "features.csv", "w", newline="", encoding="utf-8")
        self._ef = open(self.dir / "events.csv", "w", newline="", encoding="utf-8")
        self._fw = csv.DictWriter(self._ff, FEATURE_COLS, extrasaction="ignore")
        self._ew = csv.DictWriter(self._ef, EVENT_COLS)
        self._fw.writeheader()
        self._ew.writeheader()
        self.driver = "L"
        self.task = ""
        self.closed = False
        self.meta = {"pair": pair, "started": time.strftime("%Y-%m-%d %H:%M", time.localtime(start_t or time.time())),
                     "app": "PairWatch", **(meta or {})}
        (self.dir / "meta.json").write_text(json.dumps(self.meta, indent=1), encoding="utf-8")
        self.event("start", t=start_t)

    def feature(self, row: dict):
        with self._lock:
            if not self.closed:
                self._fw.writerow(row)

    def event(self, type_: str, detail="", t: float | None = None, driver: str | None = None):
        with self._lock:
            if self.closed:
                return
            self._ew.writerow({"t": round(t or time.time(), 3), "type": type_, "driver": driver or self.driver,
                               "task": self.task, "detail": json.dumps(detail) if not isinstance(detail, str) else detail})
            if type_ != "key":
                self._ef.flush()

    def save_code(self, code: str, n: int):
        (self.dir / "code" / f"{safe_name(self.task)}_{n:02d}.cpp").write_text(code, encoding="utf-8")

    def close(self, t: float | None = None):
        self.event("end", t=t)
        with self._lock:
            self.closed = True
            self._ff.close()
            self._ef.close()


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def open_folder(path: Path):
    import os
    import subprocess
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
