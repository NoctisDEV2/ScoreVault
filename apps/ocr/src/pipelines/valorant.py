"""
Valorant OCR pipeline — EasyOCR/GPU with X-coordinate column bucketing.

Scoreboard columns (left to right):
  Agent icon | Name | ACS | K / D / A | ECON RATING | FIRST BLOODS | PLANTS | DEFUSES

Team assignment:
  Top 5 rows  = Defender  (blue side)
  Bottom 5 rows = Attacker (red side)
"""

import re
import logging
import cv2
import numpy as np

from .base import BasePipeline

log = logging.getLogger(__name__)

# Column X ranges as fraction of ROI width (after cropping agent icons).
# Calibrated from Valorant 1920x1080 scoreboard.
# ROI x-span: x1=0.155*W to x2=0.640*W  (adjusted to not clip first char)
# Calibrated from val-test-01.png debug output (x_frac per column):
#   name~0.037  acs~0.449  k~0.584  d~0.638  a~0.691  econ~0.791  fb~0.965
COL_BINS = {
    "name":  (0.00, 0.40),
    "acs":   (0.40, 0.54),
    "k":     (0.54, 0.62),
    "d":     (0.62, 0.68),
    "a":     (0.68, 0.77),
    "econ":  (0.77, 0.92),
    "fb":    (0.92, 1.00),
}


def x_bucket(x_frac):
    """Return column name for a given x fraction of ROI width, or None."""
    for col, (lo, hi) in COL_BINS.items():
        if lo <= x_frac < hi:
            return col
    return None


class ValorantPipeline(BasePipeline):
    game = "Valorant"

    def preprocess(self, img):
        h, w = img.shape[:2]
        x1 = int(w * 0.155)
        x2 = int(w * 0.640)
        y1 = int(h * 0.222)
        y2 = int(h * 0.800)
        roi = img[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # Simple fixed threshold — best balance found across test images.
        # Single-digit D/A values that EasyOCR misses will trigger reviewRequired.
        _, thresh = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY_INV)

        rh, rw = thresh.shape
        scaled = cv2.resize(thresh, (rw * 2, rh * 2), interpolation=cv2.INTER_CUBIC)
        self._roi_w = rw * 2
        return scaled

    def parse(self, raw_text, ocr_results):
        if not ocr_results:
            log.warning("[VAL] No OCR results")
            return []

        roi_w = getattr(self, '_roi_w', 1)

        # ── Group detections into rows by Y coordinate ────────────────────────
        sorted_results = sorted(ocr_results, key=lambda r: r[0][0][1])
        rows = []
        current_row = []
        prev_y = None
        ROW_TOLERANCE = 20

        for bbox, text, conf in sorted_results:
            y = (bbox[0][1] + bbox[2][1]) / 2
            x = bbox[0][0]
            if prev_y is None or abs(y - prev_y) <= ROW_TOLERANCE:
                current_row.append((x, text, conf))
                prev_y = y if prev_y is None else (prev_y + y) / 2
            else:
                if current_row:
                    rows.append(sorted(current_row, key=lambda t: t[0]))
                current_row = [(x, text, conf)]
                prev_y = y
        if current_row:
            rows.append(sorted(current_row, key=lambda t: t[0]))

        log.info("[VAL] Detected %d rows total", len(rows))

        # ── Filter out header rows ────────────────────────────────────────────
        HEADER_KEYWORDS = {'sorted', 'score', 'kda', 'rating', 'combat', 'bloods', 'individually'}
        player_rows = []
        for row in rows:
            row_text = " ".join(t.lower() for _, t, _ in row)
            if any(kw in row_text for kw in HEADER_KEYWORDS):
                continue
            tokens = [t for _, t, _ in row]
            if len(tokens) < 2:
                continue
            player_rows.append(row)

        log.info("[VAL] Player rows after filter: %d", len(player_rows))

        # ── Parse each player row using X-coordinate column bucketing ─────────
        players = []
        for row in player_rows[:10]:
            cols = {"name": [], "acs": [], "k": [], "d": [], "a": [], "econ": [], "fb": []}

            for x, text, conf in row:
                x_frac = x / roi_w
                col = x_bucket(x_frac)
                if col:
                    cols[col].append(text)

            # Build name from name-column tokens, skip pure numbers
            name_parts = [t for t in cols["name"] if not re.fullmatch(r'[\d/]+', t.strip())]
            name = self.clean_name(" ".join(name_parts))

            def first_int(tokens, default=0):
                for t in tokens:
                    v = self.safe_int(t)
                    if v > 0 or re.fullmatch(r'\d+', t.strip()):
                        return v
                return default

            acs  = first_int(cols["acs"])
            k    = first_int(cols["k"])
            d    = first_int(cols["d"])
            a    = first_int(cols["a"])
            econ = first_int(cols["econ"])
            fb   = first_int(cols["fb"])

            if not name:
                log.debug("[VAL] Skipping row with no name: %s", [t for _, t, _ in row])
                continue

            log.debug("[VAL] Row parsed: name=%s acs=%d k=%d d=%d a=%d econ=%d fb=%d",
                      name, acs, k, d, a, econ, fb)

            players.append({
                "name":    name,
                "team":    "",
                "kills":   k,
                "deaths":  d,
                "assists": a,
                "stats":   {"acs": acs, "adr": econ, "firstBloods": fb},
            })

        # ── Assign teams ──────────────────────────────────────────────────────
        for i, p in enumerate(players):
            p["team"] = "Defender" if i < 5 else "Attacker"

        # ── Score from raw text ───────────────────────────────────────────────
        score_match = re.search(r'\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b', raw_text)
        self._last_result = None
        if score_match:
            sa, sb = int(score_match.group(1)), int(score_match.group(2))
            winner = "Defender" if sa > sb else "Attacker"
            self._last_result = {"teamDefender": sa, "teamAttacker": sb, "winner": winner}
            log.info("[VAL] Score: %d-%d winner=%s", sa, sb, winner)

        if not players:
            log.warning("[VAL] No players parsed — raw text:\n%s", raw_text)

        return players

    def normalize(self, players, confidence):
        canonical = super().normalize(players, confidence)
        if getattr(self, "_last_result", None):
            canonical["result"] = self._last_result
        return canonical
