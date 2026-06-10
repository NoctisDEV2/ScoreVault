"""
Base OCR pipeline using EasyOCR with NVIDIA GPU acceleration.
Falls back to CPU if CUDA is not available.

Flow: fetch -> preprocess -> OCR (EasyOCR/GPU) -> parse -> normalize -> score
"""

import io
import logging
import re
import datetime
import os
import urllib.request

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.75

# Initialise EasyOCR reader once (shared across all pipeline instances).
# gpu=True uses CUDA automatically; falls back to CPU if CUDA not available.
_reader = None

def get_reader():
    global _reader
    if _reader is None:
        import easyocr
        import torch
        use_gpu = torch.cuda.is_available()
        log.info("[easyocr] Initialising reader — GPU=%s", use_gpu)
        _reader = easyocr.Reader(['en'], gpu=use_gpu, verbose=False)
        log.info("[easyocr] Reader ready (device=%s)", "CUDA" if use_gpu else "CPU")
    return _reader


class BasePipeline:
    game = "Unknown"

    # ── Image fetch ───────────────────────────────────────────────────────────

    def fetch_image(self, url):
        if os.path.exists(url):
            pil_img = Image.open(url).convert("RGB")
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "ScoreVault-OCR/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            pil_img = Image.open(io.BytesIO(data)).convert("RGB")
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    # ── Preprocessing ─────────────────────────────────────────────────────────

    def preprocess(self, img):
        """
        Default: upscale 2x for better OCR on small text.
        Subclasses override to add game-specific ROI cropping.
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        scaled = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        return scaled

    # ── EasyOCR engine ────────────────────────────────────────────────────────

    def ocr_image(self, img):
        """
        Run EasyOCR on a preprocessed image.
        Returns list of (bbox, text, confidence) tuples sorted top-to-bottom.
        """
        reader = get_reader()
        results = reader.readtext(img, detail=1, paragraph=False)
        # Sort by vertical position (top of bounding box)
        results.sort(key=lambda r: r[0][0][1])
        return results

    def results_to_text(self, results):
        """Convert EasyOCR results to a plain text string (one line per detection)."""
        lines = []
        prev_y = None
        line_tokens = []
        for bbox, text, conf in results:
            y = bbox[0][1]
            if prev_y is not None and abs(y - prev_y) > 15:
                lines.append(" ".join(line_tokens))
                line_tokens = []
            line_tokens.append(text)
            prev_y = y
        if line_tokens:
            lines.append(" ".join(line_tokens))
        return "\n".join(lines)

    def score_confidence(self, results):
        """Mean confidence across all detected text boxes."""
        if not results:
            return 0.0
        return round(sum(r[2] for r in results) / len(results), 4)

    # ── Abstract parse / normalize ────────────────────────────────────────────

    def parse(self, raw_text, ocr_results):
        raise NotImplementedError

    def normalize(self, players, confidence):
        review = confidence < CONFIDENCE_THRESHOLD
        return {
            "schemaVersion": "1.0",
            "game": self.game,
            "matchId": self._generate_match_id(),
            "players": players,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "ocr": {
                "engine": "easyocr-gpu",
                "confidence": confidence,
                "reviewRequired": review,
            },
        }

    def _generate_match_id(self):
        import uuid
        prefix = self.game[:3].upper()
        return prefix + uuid.uuid4().hex[:6].upper()

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self, image_url):
        log.info("[%s] Fetching image: %s", self.game, image_url)
        img = self.fetch_image(image_url)
        preprocessed = self.preprocess(img)

        log.info("[%s] Running EasyOCR", self.game)
        ocr_results = self.ocr_image(preprocessed)
        raw_text = self.results_to_text(ocr_results)
        log.info("[%s] OCR text:\n%s", self.game, raw_text[:600])

        confidence = self.score_confidence(ocr_results)
        log.info("[%s] Confidence: %.4f", self.game, confidence)

        players = self.parse(raw_text, ocr_results)
        canonical = self.normalize(players, confidence)
        return canonical, confidence, canonical["ocr"]["reviewRequired"]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def safe_int(val, default=0):
        try:
            return int(re.sub(r"[^0-9\-]", "", str(val)))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def clean_name(val):
        return val.strip().strip("#").strip()
