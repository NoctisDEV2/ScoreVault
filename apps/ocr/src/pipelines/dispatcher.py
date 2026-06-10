"""
ScoreVault match data dispatcher.

Priority order for Valorant and LoL:
  1. Riot API       (official data, perfect accuracy, requires RIOT_API_KEY)
  2. Gemini Vision  (AI screenshot parsing, requires GEMINI_API_KEY)
  3. EasyOCR/GPU    (local OCR fallback, no API key needed)

For CS2: Gemini → EasyOCR (no official API client yet).

Returns: (canonical_json: dict, confidence: float, review_required: bool)
"""

import logging
import os

from gemini_client import GeminiVisionClient, GeminiQuotaError, GeminiError
from .valorant import ValorantPipeline
from .cs2 import CS2Pipeline
from .lol import LoLPipeline

log = logging.getLogger(__name__)

_EASYOCR_PIPELINES = {
    "Valorant": ValorantPipeline(),
    "CS2":      CS2Pipeline(),
    "LoL":      LoLPipeline(),
}

_gemini = GeminiVisionClient()


def dispatch_riot(game: str, riot_id_a: str, riot_id_b: str, match_id: str = None, queue: int = None):
    """
    Fetch match data via official Riot API.
    Returns (canonical_json, confidence, review_required).

    queue is only used for LoL (defaults to 420 Ranked Solo; pass 0 or None for all queues).
    """
    if game == "Valorant":
        from .riot_valorant import ValorantRiotPipeline
        pipeline = ValorantRiotPipeline()
        canonical, _ = pipeline.run(riot_id_a, riot_id_b, match_id=match_id)
        return canonical, 1.0, False

    if game == "LoL":
        from .riot_lol import LoLRiotPipeline
        pipeline = LoLRiotPipeline()
        kwargs = {"match_id": match_id}
        if queue is not None:
            kwargs["queue"] = queue
        canonical, _ = pipeline.run(riot_id_a, riot_id_b, **kwargs)
        return canonical, 1.0, False

    raise ValueError(f"No official API pipeline for game: {game}")


def dispatch(game: str, image_url: str):
    """
    Screenshot-based dispatch (bot upload flow).
    Tries Gemini Vision first, falls back to EasyOCR.
    Returns (canonical_json, confidence, review_required).
    """
    if game not in _EASYOCR_PIPELINES:
        raise ValueError(f"Unsupported game: {game}")

    # Primary: Gemini Vision
    try:
        log.info("[dispatcher] Using Gemini Vision for game=%s", game)
        canonical = _gemini.parse(game, image_url)
        if "ocr" not in canonical:
            canonical["ocr"] = {"engine": "gemini-1.5-flash", "confidence": 0.97, "reviewRequired": False}
        confidence = canonical["ocr"].get("confidence", 0.97)
        review_required = canonical["ocr"].get("reviewRequired", False)
        log.info("[dispatcher] Gemini succeeded confidence=%.4f", confidence)
        return canonical, confidence, review_required
    except GeminiQuotaError as e:
        log.warning("[dispatcher] Gemini quota exceeded, falling back to EasyOCR: %s", e)
    except GeminiError as e:
        log.warning("[dispatcher] Gemini error, falling back to EasyOCR: %s", e)

    # Fallback: EasyOCR (GPU if CUDA available, else CPU)
    log.info("[dispatcher] Using EasyOCR fallback for game=%s", game)
    return _EASYOCR_PIPELINES[game].run(image_url)
