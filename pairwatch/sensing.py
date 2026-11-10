"""Camera + microphone -> numbers, five times a second. No frame or sound is stored.

The camera loop finds up to two faces (MediaPipe face mesh, bundled offline),
turns each into head direction and mouth opening, and forgets the image. The
microphone loop keeps only loudness, to decide 'someone is speaking'.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque

import numpy as np

from .attribution import Calibration, assign_sides, attribute_speaker, face_features

TICK = 0.2  # seconds between logged rows (5 Hz)


class FaceTracker:
    def __init__(self):
        import mediapipe as mp
        self.mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False, max_num_faces=2, refine_landmarks=False,
            min_detection_confidence=0.5, min_tracking_confidence=0.5)

    def process(self, frame_bgr) -> dict:
        import cv2
        rgb = cv2.cvtColor(cv2.flip(frame_bgr, 1), cv2.COLOR_BGR2RGB)  # mirror: seats match the screen
        res = self.mesh.process(rgb)
        faces = []
        for lm in (res.multi_face_landmarks or []):
            pts = np.array([[p.x, p.y] for p in lm.landmark], np.float32)
            f = face_features(pts)
            f["box"] = (float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max()))
            faces.append(f)
        return assign_sides(faces)

    def close(self):
        self.mesh.close()


class Microphone:
    """Loudness every 50 ms; speech = clearly louder than the room's recent noise floor."""

    def __init__(self, device=None, rate: int = 16000):
        self.rms = deque(maxlen=400)  # (time, rms), ~20 s
        self.ok, self.error = False, ""
        try:
            import sounddevice as sd
            self.stream = sd.InputStream(samplerate=rate, blocksize=rate // 20, channels=1,
                                         device=device, callback=self._cb)
            self.stream.start()
            self.ok = True
        except Exception as e:  # no microphone, driver problem, permission
            self.error = str(e)

    def _cb(self, indata, frames, t, status):
        self.rms.append((time.time(), float(np.sqrt(np.mean(np.square(indata[:, 0]))))))

    def level(self) -> float:
        return self.rms[-1][1] if self.rms else 0.0

    def speech(self, now: float, window: float = TICK) -> bool:
        if len(self.rms) < 20:
            return False
        vals = np.array([r for _, r in self.rms])
        thr = max(np.percentile(vals, 20) * 2.5, 0.004)
        recent = [r for t, r in self.rms if t >= now - window]
        return bool(recent) and np.mean(np.array(recent) > thr) >= 0.5

    def close(self):
        if self.ok:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass


class SensorThread(threading.Thread):
    """Runs camera + microphone in the background and calls on_row(dict) at 5 Hz."""

    def __init__(self, on_row, camera: int = 0, mic_device=None, image_source: str | None = None):
        super().__init__(daemon=True)
        self.on_row, self.camera, self.mic_device, self.image_source = on_row, camera, mic_device, image_source
        self.stop_flag = threading.Event()
        self.calib = {"L": Calibration(), "R": Calibration()}
        self.calib_target: str | None = None      # set by the UI during calibration
        self.status = {"faces": 0, "camera": False, "mic": False, "speaker": "", "level": 0.0, "error": ""}
        self.preview = None                        # small annotated frame for the calibration screen
        self.want_preview = False
        self._mouth = {"L": deque(maxlen=12), "R": deque(maxlen=12)}
        self._quiet_act = {"L": deque(maxlen=150), "R": deque(maxlen=150)}

    def _activity(self, side: str):
        m = self._mouth[side]
        return float(np.std([v for _, v in m])) if len(m) >= 4 else None

    def _floor(self, side: str) -> float:
        q = self._quiet_act[side]
        return max(1.8 * float(np.median(q)), 0.012) if len(q) >= 10 else 0.02

    def run(self):
        import cv2
        try:
            tracker = FaceTracker()
        except Exception as e:
            self.status["error"] = f"face model: {e}"
            return
        if self.image_source:
            frame_img = cv2.imread(self.image_source)
            cap = None
        else:
            cap = cv2.VideoCapture(self.camera, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(self.camera)
            if not cap.isOpened():
                cap = cv2.VideoCapture(self.camera)
        self.status["camera"] = bool(self.image_source) or (cap is not None and cap.isOpened())
        mic = Microphone(self.mic_device)
        self.status["mic"] = mic.ok
        if not mic.ok:
            self.status["error"] = "microphone: " + mic.error[:120]
        next_tick = time.time()
        sides: dict = {}
        try:
            while not self.stop_flag.is_set():
                if cap is not None:
                    ok, frame = cap.read()
                    if not ok:
                        time.sleep(0.05)
                        continue
                else:
                    frame = frame_img.copy()
                    time.sleep(0.03)
                now = time.time()
                sides = tracker.process(frame)
                for s, f in sides.items():
                    self._mouth[s].append((now, f["mouth"]))
                    if self.calib_target:
                        self.calib[s].add(self.calib_target, f)
                if self.want_preview:
                    self.preview = self._draw_preview(frame, sides)
                del frame  # nothing of the image is kept
                if now >= next_tick:
                    next_tick = now + TICK
                    speech = mic.speech(now) if mic.ok else False
                    act = {s: self._activity(s) for s in ("L", "R")}
                    if not speech:
                        for s in ("L", "R"):
                            if act[s] is not None:
                                self._quiet_act[s].append(act[s])
                    speaker = attribute_speaker(speech, act["L"], act["R"], self._floor("L"), self._floor("R"))
                    row = {"t": round(now, 2), "speech": int(speech), "level": round(mic.level(), 5) if mic.ok else "",
                           "speaker": speaker}
                    for s, partner_side in (("L", 1), ("R", -1)):
                        f = sides.get(s)
                        row[f"face_{s}"] = int(f is not None)
                        row[f"yaw_{s}"] = round(f["yaw"], 3) if f else ""
                        row[f"pitch_{s}"] = round(f["pitch"], 3) if f else ""
                        row[f"mouth_{s}"] = round(act[s], 4) if f and act[s] is not None else ""
                        row[f"look_{s}"] = self.calib[s].region(f, partner_side) if f else ""
                    self.status.update(faces=len(sides), speaker=speaker, level=row["level"] or 0.0)
                    self.on_row(row)
        finally:
            if cap is not None:
                cap.release()
            mic.close()
            tracker.close()

    def _draw_preview(self, frame, sides):
        """Camera check view: the WHOLE picture is pixelated, so nobody is recognisable
        (even a face the model missed), but positions are clear enough to set up the laptop."""
        import cv2
        img = cv2.flip(frame, 1)
        h, w = img.shape[:2]
        img = cv2.resize(cv2.resize(img, (max(1, w // 16), max(1, h // 16)), interpolation=cv2.INTER_AREA),
                         (w, h), interpolation=cv2.INTER_NEAREST)
        for s, f in sides.items():
            x1, y1, x2, y2 = f["box"]
            c = (181, 109, 47) if s == "L" else (60, 140, 230)
            cv2.rectangle(img, (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h)), c, 4)
            label = "LEFT student" if s == "L" else "RIGHT student"
            org = (int(x1 * w), max(int(y1 * h) - 12, 30))
            cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 6, cv2.LINE_AA)
            cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, 1.2, c, 3, cv2.LINE_AA)
        return cv2.resize(img, (480, int(480 * h / w)))

    def stop(self):
        self.stop_flag.set()
