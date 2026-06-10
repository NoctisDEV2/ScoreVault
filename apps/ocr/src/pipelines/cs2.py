"""
CS2 OCR pipeline.

Scoreboard column order (left → right):
  Name | K | A | D | ADR | HS%

Note: CS2 shows K/A/D, NOT K/D/A like Valorant. We map to canonical K/D/A.
"""

import re
import logging
from .base import BasePipeline

log = logging.getLogger(__name__)


class CS2Pipeline(BasePipeline):
    game = "CS2"

    # Match: Name  K  A  D  ADR  HS%
    ROW_RE = re.compile(
        r"([A-Za-z0-9_#\-\.]{2,20})\s+"  # name
        r"(\d{1,3})\s+"                   # K
        r"(\d{1,3})\s+"                   # A
        r"(\d{1,3})\s+"                   # D  ← note: CS2 is K/A/D
        r"(\d{1,3}\.?\d*)\s+"             # ADR
        r"(\d{1,3})%?"                     # HS%
    )

    SCORE_RE = re.compile(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b")

    def parse(self, raw_text: str, ocr_data: dict) -> list[dict]:
        players = []
        team = "CT"
        team_switch_done = False

        score_match = self.SCORE_RE.search(raw_text)
        self._last_result = None
        if score_match:
            sa, sb = int(score_match.group(1)), int(score_match.group(2))
            winner = "CT" if sa > sb else "T"
            self._last_result = {"teamCT": sa, "teamT": sb, "winner": winner}

        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                if players and not team_switch_done:
                    team_switch_done = True
                    team = "T"
                continue

            m = self.ROW_RE.search(line)
            if m:
                name, k, a, d, adr, hs = m.groups()
                players.append({
                    "name":    self.clean_name(name),
                    "team":    team,
                    "kills":   self.safe_int(k),
                    "deaths":  self.safe_int(d),   # map D col → deaths
                    "assists": self.safe_int(a),
                    "stats": {
                        "adr": float(adr) if adr else 0.0,
                        "hsPercent": self.safe_int(hs),
                    },
                })

        if not players:
            log.warning("[CS2] No players parsed")
        return players

    def normalize(self, players, confidence):
        canonical = super().normalize(players, confidence)
        if self._last_result:
            canonical["result"] = self._last_result
        return canonical
