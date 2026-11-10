"""Condition test: when does webcam attention sensing work, and when does it fail?

One volunteer at a time follows on-screen prompts while the teacher records the
conditions (light, distance, face covering, glasses, camera). Each trial has
  1. a calibration pass: look at the middle, top and bottom of the screen;
  2. a test pass, in shuffled order: top, middle, bottom, turn left, turn right, look down.
Only the test pass is scored, against a calibration made from the separate first
pass, so the score is not inflated by testing on the calibration data.

Per frame only numbers are kept: face found, head yaw/pitch, face size and the
picture's average brightness (an objective check of the light condition).
"""
from __future__ import annotations

import csv
import json
import random
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .attribution import Calibration

CALIB_TARGETS = ("middle", "top", "bottom")
TEST_TARGETS = ("top", "middle", "bottom", "left", "right", "down")
LABELS = TEST_TARGETS + ("no face",)

CONDITIONS = {  # factor -> options (first = default)
    "light": ["good", "dim", "window behind", "power cut / UPS light"],
    "distance": ["front (≈60 cm)", "middle (≈1.5 m)", "back (≈3 m)"],
    "face_covering": ["none", "headscarf", "niqab / face covered"],
    "glasses": ["no", "yes"],
    "camera": ["laptop built-in", "USB webcam"],
}

PROMPTS = {
    "middle": "Look at the red dot in the MIDDLE of the screen",
    "top": "Look at the red dot at the TOP of the screen",
    "bottom": "Look at the red dot at the BOTTOM of the screen",
    "left": "Turn your head to the LEFT, as if looking at a partner on your left",
    "right": "Turn your head to the RIGHT, as if looking at a partner on your right",
    "down": "Look DOWN at the desk, as if reading notes",
}


def classify(f: dict | None, calib: Calibration, yaw_tol: float = 0.22) -> str:
    """Head direction -> one of TEST_TARGETS (or 'no face'), using this person's calibration.
    The picture is mirrored, so turning to your own right moves the nose to the image right."""
    if f is None:
        return "no face"
    yaw0 = float(np.median(calib.yaw_samples)) if calib.yaw_samples else 0.0
    dyaw = f["yaw"] - yaw0
    if dyaw > 1.6 * yaw_tol:
        return "right"
    if dyaw < -1.6 * yaw_tol:
        return "left"
    c = calib.centres()
    if not calib.ready:
        return "middle"
    span = abs(c["bottom"] - c["top"]) + 1e-6
    lo, hi = sorted((c["top"], c["bottom"]))
    down_is_high = c["bottom"] >= c["top"]
    if (down_is_high and f["pitch"] > hi + 0.75 * span) or (not down_is_high and f["pitch"] < lo - 0.75 * span):
        return "down"
    return min(("top", "middle", "bottom"), key=lambda r: abs(f["pitch"] - c[r]))


def score(frames: list[dict]) -> dict:
    """frames: dicts with phase ('calib'/'test'), target, settled (bool), face, yaw, pitch, size, brightness."""
    calib = Calibration()
    for fr in frames:
        if fr["phase"] == "calib" and fr["settled"] and fr["face"]:
            calib.add(fr["target"], fr)
    test = [fr for fr in frames if fr["phase"] == "test" and fr["settled"]]
    preds = [classify(fr if fr["face"] else None, calib) for fr in test]
    out = {"calibrated": calib.ready, "test_frames": len(test)}
    if not test:
        return out
    face = np.array([bool(fr["face"]) for fr in test])
    correct = np.array([p == fr["target"] for p, fr in zip(preds, test)])
    out["face_found"] = round(float(face.mean()), 3)
    out["accuracy_all_frames"] = round(float(correct.mean()), 3)                 # no face counts as wrong
    out["accuracy_when_face_found"] = round(float(correct[face].mean()), 3) if face.any() else None
    out["per_target"] = {}
    for t in TEST_TARGETS:
        m = np.array([fr["target"] == t for fr in test])
        if m.any():
            out["per_target"][t] = {"face_found": round(float(face[m].mean()), 3),
                                    "accuracy": round(float(correct[m].mean()), 3)}
    out["confusion"] = {t: {p: int(sum(1 for pp, fr in zip(preds, test) if fr["target"] == t and pp == p)) for p in LABELS}
                        for t in TEST_TARGETS}
    bright = [fr["brightness"] for fr in test if fr.get("brightness") is not None]
    sizes = [fr["size"] for fr in test if fr["face"]]
    out["mean_brightness"] = round(float(np.mean(bright)), 1) if bright else None   # 0 = black, 255 = white
    out["mean_face_size"] = round(float(np.mean(sizes)), 4) if sizes else None      # eye distance / image width
    return out


def tests_root() -> Path:
    from .session import data_root
    p = data_root() / "condition_tests"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_trial(root: Path, participant: str, conditions: dict, frames: list[dict]) -> Path:
    from .session import safe_name
    d = root / f"{time.strftime('%Y-%m-%d_%H%M%S')}_{safe_name(participant)}"
    d.mkdir(parents=True, exist_ok=True)
    cols = ["t", "phase", "target", "settled", "face", "yaw", "pitch", "size", "brightness"]
    with open(d / "frames.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        for fr in frames:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in fr.items()})
    trial = {"participant": participant, "time": time.strftime("%Y-%m-%d %H:%M"), "conditions": conditions,
             "result": score(frames)}
    (d / "trial.json").write_text(json.dumps(trial, indent=1, ensure_ascii=False), encoding="utf-8")
    return d


def load_trials(root: Path) -> list[dict]:
    trials = []
    for p in sorted(root.glob("*/trial.json")):
        try:
            trials.append(json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return trials


def summarise(trials: list[dict]) -> dict:
    """For every factor and option: number of trials, mean face-found rate, mean direction accuracy."""
    out = {}
    for factor, options in CONDITIONS.items():
        rows = []
        for opt in options:
            sel = [t["result"] for t in trials if t["conditions"].get(factor) == opt and t["result"].get("test_frames")]
            if not sel:
                rows.append({"option": opt, "n": 0})
                continue
            ff = [r["face_found"] for r in sel]
            acc = [r["accuracy_all_frames"] for r in sel]
            accf = [r["accuracy_when_face_found"] for r in sel if r.get("accuracy_when_face_found") is not None]
            rows.append({"option": opt, "n": len(sel), "face_found": round(float(np.mean(ff)), 3),
                         "accuracy": round(float(np.mean(acc)), 3),
                         "accuracy_when_face_found": round(float(np.mean(accf)), 3) if accf else None})
        out[factor] = rows
    return out


def export_csv(trials: list[dict], path: Path):
    cols = ["participant", "time", *CONDITIONS, "face_found", "accuracy_all_frames", "accuracy_when_face_found",
            "mean_brightness", "mean_face_size", *[f"acc_{t}" for t in TEST_TARGETS]]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for t in trials:
            r = t["result"]
            w.writerow([t["participant"], t["time"], *[t["conditions"].get(k, "") for k in CONDITIONS],
                        r.get("face_found"), r.get("accuracy_all_frames"), r.get("accuracy_when_face_found"),
                        r.get("mean_brightness"), r.get("mean_face_size"),
                        *[r.get("per_target", {}).get(x, {}).get("accuracy") for x in TEST_TARGETS]])


def condition_report(root: Path, out: Path | None = None) -> Path | None:
    import html
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from .report import BLUE, CREDIT, CSS, ORANGE, _png
    trials = load_trials(root)
    if not trials:
        return None
    s = summarise(trials)
    fig, axs = plt.subplots(1, len(CONDITIONS), figsize=(14, 3.6), sharey=True)
    for ax, (factor, rows) in zip(axs, s.items()):
        rows = [r for r in rows if r["n"]]
        x = np.arange(len(rows))
        ax.bar(x - 0.2, [r["face_found"] for r in rows], 0.38, color=BLUE, label="face found")
        ax.bar(x + 0.2, [r["accuracy"] for r in rows], 0.38, color=ORANGE, label="direction correct")
        ax.set_xticks(x, [f"{r['option']}\n(n={r['n']})" for r in rows], fontsize=7)
        ax.set_title(factor.replace("_", " "), fontsize=10)
        ax.set_ylim(0, 1.05)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axs[0].set_ylabel("share of test frames")
    axs[0].legend(fontsize=8, frameon=False, loc="lower left")
    fig.tight_layout()
    img = _png(fig)
    plt.close(fig)

    def pc(v):
        return "–" if v is None else f"{100 * v:.0f}%"

    tables = ""
    for factor, rows in s.items():
        body = "".join(
            f"<tr><td>{html.escape(r['option'])}</td><td>{r['n']}</td><td>{pc(r.get('face_found'))}</td>"
            f"<td>{pc(r.get('accuracy'))}</td><td>{pc(r.get('accuracy_when_face_found'))}</td></tr>"
            for r in rows)
        tables += (f"<h3>{factor.replace('_', ' ').capitalize()}</h3><table><tr><th>Condition</th><th>Trials</th>"
                   f"<th>Face found</th><th>Direction correct</th><th>Correct when face found</th></tr>{body}</table>")
    # per-target accuracy over all trials
    pt = {t: [tr["result"]["per_target"][t]["accuracy"] for tr in trials if t in tr["result"].get("per_target", {})] for t in TEST_TARGETS}
    pt_rows = "".join(f"<tr><td>{t}</td><td>{100 * np.mean(v):.0f}%</td><td>{len(v)}</td></tr>" for t, v in pt.items() if v)
    export_csv(trials, root / "all_trials.csv")
    doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>PairWatch – condition test</title><style>{CSS}</style></head><body>
<h1>When does webcam attention sensing work?</h1><div class="sub">{len(trials)} trials · condition test</div>
<div class="note">Each trial: one volunteer looked at the top, middle and bottom of the screen, turned left and right, and looked down, in random order.
<b>Face found</b> = share of those moments in which the camera found a face at all. <b>Direction correct</b> = share in which PairWatch's head-direction estimate matched the instruction (a missing face counts as wrong).
Only numbers were recorded, no pictures.</div>
<img src="{img}">
{tables}
<h3>By instruction (all trials)</h3><table><tr><th>Instruction</th><th>Direction correct</th><th>Trials</th></tr>{pt_rows}</table>
<div class="note">With few trials per condition, differences are first evidence, not proof. Each volunteer should, where possible, do the same trial under several conditions, so that conditions are compared within the same person.
All numbers per trial are in <code>all_trials.csv</code> next to this report.</div>
<footer>PairWatch · {CREDIT}</footer></body></html>"""
    out = out or (root.parent / "condition_report.html")
    out.write_text(doc, encoding="utf-8")
    return out


@dataclass
class Step:
    phase: str
    target: str
    seconds: float


def trial_plan(rng: random.Random | None = None, hold: float = 3.0) -> list[Step]:
    rng = rng or random.Random()
    test = list(TEST_TARGETS)
    rng.shuffle(test)
    return [Step("calib", t, hold) for t in CALIB_TARGETS] + [Step("test", t, hold) for t in test]


class TrialRecorder(threading.Thread):
    """Camera loop for one volunteer: keeps the latest numbers and, during a trial,
    appends one row per frame labelled with the current instruction."""

    def __init__(self, camera: int = 0, image_source: str | None = None):
        super().__init__(daemon=True)
        self.camera, self.image_source = camera, image_source
        self.stop_flag = threading.Event()
        self.phase = self.target = None
        self.step_started = 0.0
        self.settle = 1.0
        self.frames: list[dict] = []
        self.recording = False
        self.latest: dict | None = None
        self.preview = None
        self.error = ""

    def run(self):
        import cv2
        from .sensing import FaceTracker
        try:
            tracker = FaceTracker()
        except Exception as e:
            self.error = f"face model: {e}"
            return
        cap = None
        img = cv2.imread(self.image_source) if self.image_source else None
        if img is None:
            cap = cv2.VideoCapture(self.camera, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(self.camera)
            if not cap.isOpened():
                cap = cv2.VideoCapture(self.camera)
            if not cap.isOpened():
                self.error = "camera could not be opened"
        try:
            while not self.stop_flag.is_set():
                if cap is not None:
                    ok, frame = cap.read()
                    if not ok:
                        time.sleep(0.05)
                        continue
                else:
                    if img is None:
                        time.sleep(0.1)
                        continue
                    frame = img.copy()
                    time.sleep(0.04)
                now = time.time()
                bright = float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())
                sides = tracker.process(frame)
                face = max(sides.values(), key=lambda f: f["size"]) if sides else None
                self.latest = face
                if not self.recording:
                    self.preview = self._preview(frame, face)
                del frame
                if self.recording and self.target:
                    self.frames.append({"t": round(now, 3), "phase": self.phase, "target": self.target,
                                        "settled": (now - self.step_started) >= self.settle, "face": int(face is not None),
                                        "yaw": face["yaw"] if face else None, "pitch": face["pitch"] if face else None,
                                        "size": face["size"] if face else None, "brightness": round(bright, 1)})
        finally:
            if cap is not None:
                cap.release()
            tracker.close()

    def _preview(self, frame, face):
        import cv2
        img = cv2.flip(frame, 1)
        h, w = img.shape[:2]
        img = cv2.resize(cv2.resize(img, (max(1, w // 16), max(1, h // 16)), interpolation=cv2.INTER_AREA),
                         (w, h), interpolation=cv2.INTER_NEAREST)
        if face:
            x1, y1, x2, y2 = face["box"]
            cv2.rectangle(img, (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h)), (80, 175, 60), 4)
        return cv2.resize(img, (420, int(420 * h / w)))

    def begin(self, phase: str, target: str):
        self.phase, self.target, self.step_started = phase, target, time.time()

    def stop(self):
        self.stop_flag.set()
