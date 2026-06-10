"""
LoL OCR pipeline.

Scoreboard column order (left → right):
  Champion | Name | KDA (combined: K/D/A) | CS | Gold

KDA cell example: "12/3/7" — split on '/'
"""

import re
import logging
from .base import BasePipeline

log = logging.getLogger(__name__)


class LoLPipeline(BasePipeline):
    game = "LoL"

    # Match: Name  K/D/A  CS  Gold(k)
    ROW_RE = re.compile(
        r"([A-Za-z0-9_#\-\.]{2,20})\s+"  # name
        r"(\d{1,3})/(\d{1,3})/(\d{1,3})\s+"  # K / D / A
        r"(\d{1,4})\s+"                         # CS
        r"(\d{1,2}\.?\d*)[kK]?"                 # Gold (may be e.g. "12.3k")
    )

    SCORE_RE = re.compile(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b")

    def parse(self, raw_text: str, ocr_data: dict) -> list[dict]:
        players = []
        team = "Blue"
        team_switch_done = False

        score_match = self.SCORE_RE.search(raw_text)
        self._last_result = None
        if score_match:
            sb, sr = int(score_match.group(1)), int(score_match.group(2))
            winner = "Blue" if sb > sr else "Red"
            self._last_result = {"teamBlue": sb, "teamRed": sr, "winner": winner}

        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                if players and not team_switch_done:
                    team_switch_done = True
                    team = "Red"
                continue

            m = self.ROW_RE.search(line)
            if m:
                name, k, d, a, cs, gold = m.groups()
                players.append({
                    "name":    self.clean_name(name),
                    "team":    team,
                    "kills":   self.safe_int(k),
                    "deaths":  self.safe_int(d),
                    "assists": self.safe_int(a),
                    "stats": {
                        "cs":   self.safe_int(cs),
                        "gold": float(gold) if gold else 0.0,
                    },
                })

        if not players:
            log.warning("[LoL] No players parsed")
        return players

    def normalize(self, players, confidence):
        canonical = super().normalize(players, confidence)
        if self._last_result:
            canonical["result"] = self._last_result
        return canonical
