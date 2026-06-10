"""
Gemini Vision client for ScoreVault OCR.

Sends a scoreboard screenshot to Gemini and returns a validated canonical JSON object.
Falls back to Tesseract pipeline on quota/API errors.
"""

import base64
import json
import logging
import os
import re
import urllib.request
import urllib.error
import io

log = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_GEMINI_MODELS = (
    "gemini-2.0-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
)

# ── Per-game prompt templates ─────────────────────────────────────────────────

PROMPTS = {
    "Valorant": """You are parsing a Valorant match scoreboard screenshot.
Extract ONLY a JSON object — no explanation, no markdown, no code fences.

Rules:
- schemaVersion: always "1.0"
- game: "Valorant"
- matchId: generate as "VAL" + 6 random uppercase hex chars
- players: array of all players visible (typically 10, 5v5)
  - name: exact player name string
  - team: "A" for the top team (winner or first listed), "B" for the bottom team
  - kills, deaths, assists: integers from the KDA column (format is K / D / A)
  - stats.acs: integer from AVG COMBAT SCORE column
  - stats.adr: integer from ECON RATING column (if visible)
  - stats.firstBloods: integer from FIRST BLOODS column (if visible)
- result: { teamA: <score>, teamB: <score>, winner: "A" or "B" }
  Extract the large round score numbers at the top of the screen.
- timestamp: current UTC time in ISO 8601 format
- ocr.engine: "gemini-1.5-flash"
- ocr.confidence: 0.97
- ocr.reviewRequired: false

Return exactly this structure:
{
  "schemaVersion": "1.0",
  "game": "Valorant",
  "matchId": "VALxxxxxx",
  "players": [...],
  "result": {"teamA": 0, "teamB": 0, "winner": "A"},
  "timestamp": "2026-01-01T00:00:00Z",
  "ocr": {"engine": "gemini-1.5-flash", "confidence": 0.97, "reviewRequired": false}
}""",

    "CS2": """You are parsing a CS2 match scoreboard screenshot.
Extract ONLY a JSON object — no explanation, no markdown, no code fences.

Rules:
- schemaVersion: always "1.0"
- game: "CS2"
- matchId: generate as "CS2" + 6 random uppercase hex chars
- players: array of all players visible
  - name: exact player name
  - team: "CT" for Counter-Terrorist side, "T" for Terrorist side
  - kills, deaths, assists: integers (CS2 column order is K / A / D — map to kills/deaths/assists correctly)
  - stats.adr: float from ADR column
  - stats.hsPercent: integer from HS% column
- result: { teamCT: <score>, teamT: <score>, winner: "CT" or "T" }
- timestamp: current UTC time ISO 8601
- ocr.engine: "gemini-1.5-flash"
- ocr.confidence: 0.97
- ocr.reviewRequired: false

Return only the JSON object, no other text.""",

    "LoL": """You are parsing a League of Legends end-of-game scoreboard screenshot.
Extract ONLY a JSON object — no explanation, no markdown, no code fences.

Rules:
- schemaVersion: always "1.0"
- game: "LoL"
- matchId: generate as "LOL" + 6 random uppercase hex chars
- players: array of all players visible
  - name: exact summoner name
  - team: "Blue" or "Red"
  - kills, deaths, assists: integers split from the K/D/A cell
  - stats.cs: integer creep score
  - stats.gold: float gold in thousands (e.g. 12.3 for 12,300)
  - stats.champion: champion name string
- result: { teamBlue: <kills or wins>, teamRed: <kills or wins>, winner: "Blue" or "Red" }
- timestamp: current UTC time ISO 8601
- ocr.engine: "gemini-1.5-flash"
- ocr.confidence: 0.97
- ocr.reviewRequired: false

Return only the JSON object, no other text.""",
}


# ── Client ─────────────────────────────────────────────────────────────────────

class GeminiVisionClient:

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        configured_models = os.getenv("GEMINI_MODELS", "").strip()
        if configured_models:
            self.models = tuple(m.strip() for m in configured_models.split(",") if m.strip())
        else:
            self.models = DEFAULT_GEMINI_MODELS

    def _load_image_b64(self, image_path_or_url: str) -> tuple[str, str]:
        """Return (base64_data, mime_type)."""
        if os.path.exists(image_path_or_url):
            with open(image_path_or_url, "rb") as f:
                data = f.read()
            mime = "image/png" if image_path_or_url.lower().endswith(".png") else "image/jpeg"
        else:
            req = urllib.request.Request(
                image_path_or_url,
                headers={"User-Agent": "ScoreVault-OCR/1.0"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            mime = resp.headers.get("Content-Type", "image/png").split(";")[0]
        return base64.b64encode(data).decode("utf-8"), mime

    def parse(self, game: str, image_path_or_url: str) -> dict:
        """
        Call Gemini Vision and return parsed canonical JSON dict.
        Raises GeminiQuotaError on 429, GeminiError on other API failures.
        """
        if not self.api_key:
            raise GeminiError("GEMINI_API_KEY not set")

        prompt = PROMPTS.get(game)
        if not prompt:
            raise GeminiError(f"No prompt template for game: {game}")

        log.info("[gemini] Loading image for %s", game)
        img_b64, mime_type = self._load_image_b64(image_path_or_url)

        payload = json.dumps({
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": img_b64}}
                ]
            }],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 2048,
            }
        }).encode("utf-8")

        body = None
        last_error = None
        for model in self.models:
            url = f"{GEMINI_API_BASE}/{model}:generateContent?key={self.api_key}"
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                log.info("[gemini] Request succeeded using model=%s", model)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    raise GeminiQuotaError("Gemini quota exceeded")
                error_body = e.read().decode("utf-8", errors="replace")
                last_error = GeminiError(f"Gemini API error {e.code}: {error_body}")
                # Some projects/accounts expose different model ids; try next model on 404.
                if e.code == 404:
                    log.warning("[gemini] Model %s unavailable, trying next configured model", model)
                    continue
                raise last_error

        if body is None:
            if last_error:
                raise last_error
            raise GeminiError("Gemini request failed before receiving a response")

        # Extract text from response
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise GeminiError(f"Unexpected Gemini response structure: {e}\n{body}")

        log.info("[gemini] Raw response text: %s", text[:500])

        # Strip any markdown fences Gemini might add despite the prompt
        text = re.sub(r"```(?:json)?", "", text).strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            raise GeminiError(f"Gemini returned invalid JSON: {e}\nText: {text[:300]}")

        return result


class GeminiError(Exception):
    pass


class GeminiQuotaError(GeminiError):
    pass
