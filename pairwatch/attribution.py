"""Pure functions: face geometry -> head direction -> screen region; speech -> speaker.

Everything here works on numbers only (no images), so it can be tested without
a camera. Directions are simple, explainable proxies, made personal by a short
calibration at the start of each session.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# MediaPipe face-mesh landmark indices
NOSE_TIP, EYE_L_OUT, EYE_R_OUT, LIP_UP, LIP_DOWN = 1, 33, 263, 13, 14

REGIONS = ("top", "middle", "bottom")
AWAY, PARTNER, NONE = "away", "partner", ""


def face_features(pts: np.ndarray) -> dict:
    """pts: (N, 2) landmarks in image-normalised units (already mirrored).
    yaw > 0: head turned to the image right; pitch grows as the head tilts down."""
    a, b, n = pts[EYE_L_OUT], pts[EYE_R_OUT], pts[NOSE_TIP]
    eyes = (a + b) / 2
    d = float(np.linalg.norm(a - b)) + 1e-6
    return {
        "cx": float(pts[:, 0].mean()),
        "yaw": float((n[0] - eyes[0]) / d),
        "pitch": float((n[1] - eyes[1]) / d),
        "mouth": float(np.linalg.norm(pts[LIP_UP] - pts[LIP_DOWN]) / d),
        "size": d,
    }


@dataclass
class Calibration:
    """Per-student head pitch for the top / middle / bottom of the code, and head yaw
    when looking at the screen. Collected in ~10 s at the start of a session."""
    samples: dict = field(default_factory=lambda: {"top": [], "middle": [], "bottom": []})
    yaw_samples: list = field(default_factory=list)
    yaw_tol: float = 0.22

    def add(self, target: str, f: dict):
        self.samples[target].append(f["pitch"])
        self.yaw_samples.append(f["yaw"])

    @property
    def ready(self) -> bool:
        return all(len(v) >= 3 for v in self.samples.values())

    def centres(self) -> dict:
        c = {k: float(np.median(v)) for k, v in self.samples.items() if v}
        if "middle" not in c:
            c["middle"] = 0.55  # typical value when looking straight at a screen
        return c

    def region(self, f: dict, partner_side: int) -> str:
        """partner_side: +1 if the partner sits to the image right (left student), -1 otherwise."""
        yaw0 = float(np.median(self.yaw_samples)) if self.yaw_samples else 0.0
        dyaw = f["yaw"] - yaw0
        if dyaw * partner_side > 1.6 * self.yaw_tol:
            return PARTNER
        if abs(dyaw) > 1.6 * self.yaw_tol:
            return AWAY
        c = self.centres()
        if not self.ready:
            return "middle" if abs(f["pitch"] - c["middle"]) < 0.25 else AWAY
        span = abs(c["bottom"] - c["top"]) + 1e-6
        lo, hi = sorted((c["top"], c["bottom"]))
        if f["pitch"] < lo - 0.75 * span or f["pitch"] > hi + 0.75 * span:
            return AWAY  # looking above the screen or down at the keyboard / desk
        return min(REGIONS, key=lambda r: abs(f["pitch"] - c[r]))


def attribute_speaker(speech: bool, act_l: float | None, act_r: float | None,
                      floor_l: float, floor_r: float, ratio: float = 1.6) -> str:
    """Who is talking, from 'the microphone hears speech' + 'whose mouth is moving'.
    Returns 'L', 'R', 'both', '?' (speech, but no clear mouth) or '' (silence)."""
    if not speech:
        return ""
    ml = act_l is not None and act_l > floor_l
    mr = act_r is not None and act_r > floor_r
    if ml and mr:
        sl, sr = act_l / max(floor_l, 1e-6), act_r / max(floor_r, 1e-6)
        if sl > ratio * sr:
            return "L"
        if sr > ratio * sl:
            return "R"
        return "both"
    if ml:
        return "L"
    if mr:
        return "R"
    return "?"


def assign_sides(faces: list[dict]) -> dict:
    """Two faces: the one further left in the (mirrored) image is the left student.
    One face: decide by which half of the image it is in."""
    faces = sorted(faces, key=lambda f: f["cx"])[:2]
    if len(faces) == 2:
        return {"L": faces[0], "R": faces[1]}
    if len(faces) == 1:
        return {"L" if faces[0]["cx"] < 0.5 else "R": faces[0]}
    return {}
