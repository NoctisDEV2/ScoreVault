"""
League of Legends Riot API pipeline.

Flow:
  1. Resolve Riot ID (gameName#tagLine) → PUUID for both players
  2. Fetch match history for each player (list of matchIds, queue=5 for Ranked Solo)
  3. Find most recent common matchId
  4. Fetch full match data from Riot Match v5 API
  5. Map to canonical JSON schema

Requires: RIOT_API_KEY and LOL_REGION in .env
  LOL_REGION: americas | europe | asia | sea  (routing cluster, not platform)
"""

import os
import json
import logging
import datetime
import urllib.request
import urllib.error
import urllib.parse

log = logging.getLogger(__name__)

# LoL Match v5 uses a regional routing cluster (not platform routing).
# Cluster → covers these platforms:
#   americas  → NA1, BR1, LA1, LA2
#   europe    → EUW1, EUN1, TR1, RU
#   asia      → KR, JP1
#   sea       → OC1, PH2, SG2, TH2, TW2, VN2
LOL_REGION   = os.getenv("LOL_REGION", "americas")
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "")

ACCOUNT_BASE = "https://americas.api.riotgames.com"   # account-v1 always routes via americas
MATCH_BASE   = f"https://{LOL_REGION}.api.riotgames.com"


def _get(base: str, path: str) -> dict:
    """Authenticated GET to the Riot API."""
    if not RIOT_API_KEY:
        raise RuntimeError("RIOT_API_KEY not set in environment")
    url = base + path
    req = urllib.request.Request(
        url,
        headers={
            "X-Riot-Token": RIOT_API_KEY,
            "Accept": "application/json",
        },
    )
    log.debug("[riot-lol] GET %s", url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Riot API {e.code} on {path}: {body}") from e


def get_puuid(game_name: str, tag_line: str) -> str:
    """Resolve gameName#tagLine → PUUID via account-v1."""
    name_enc = urllib.parse.quote(game_name)
    tag_enc  = urllib.parse.quote(tag_line)
    data = _get(ACCOUNT_BASE, f"/riot/account/v1/accounts/by-riot-id/{name_enc}/{tag_enc}")
    return data["puuid"]


def get_match_history(puuid: str, count: int = 20, queue: int = None) -> list[str]:
    """
    Return up to `count` recent matchIds for a PUUID.
    queue=420 → Ranked Solo/Duo, queue=None → all queues.
    """
    params = f"start=0&count={count}"
    if queue is not None:
        params += f"&queue={queue}"
    enc = urllib.parse.quote(puuid)
    return _get(MATCH_BASE, f"/lol/match/v5/matches/by-puuid/{enc}/ids?{params}")


def get_match(match_id: str) -> dict:
    """Fetch full match data by matchId from Match v5."""
    return _get(MATCH_BASE, f"/lol/match/v5/matches/{match_id}")


def parse_match_to_canonical(match: dict) -> dict:
    """
    Map Riot LoL Match v5 JSON → ScoreVault canonical schema.

    Riot team IDs: 100 (Blue/Bottom side), 200 (Red/Top side).
    We map 100 → "Blue", 200 → "Red".
    """
    info      = match.get("info", {})
    metadata  = match.get("metadata", {})
    riot_id   = metadata.get("matchId", "")

    participants = info.get("participants", [])
    teams        = {t["teamId"]: t for t in info.get("teams", [])}

    blue = teams.get(100, {})
    red  = teams.get(200, {})

    # Win/loss is stored per-team as a boolean
    blue_won = blue.get("win", False)
    winner   = "Blue" if blue_won else "Red"

    # Objectives for score-like display (towers, dragons, kills) — use team kills
    blue_kills = sum(p.get("kills", 0) for p in participants if p.get("teamId") == 100)
    red_kills  = sum(p.get("kills", 0) for p in participants if p.get("teamId") == 200)

    canonical_players = []
    for p in participants:
        team_id = p.get("teamId")
        team    = "Blue" if team_id == 100 else "Red"

        cs = p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0)

        canonical_players.append({
            "name":    p.get("riotIdGameName") or p.get("summonerName", "unknown"),
            "team":    team,
            "kills":   p.get("kills", 0),
            "deaths":  p.get("deaths", 0),
            "assists": p.get("assists", 0),
            "stats": {
                "cs":              cs,
                "gold":            p.get("goldEarned", 0),
                "champion":        p.get("championName", ""),
                "damageDealt":     p.get("totalDamageDealtToChampions", 0),
                "visionScore":     p.get("visionScore", 0),
                "wardsPlaced":     p.get("wardsPlaced", 0),
                "doubleKills":     p.get("doubleKills", 0),
                "tripleKills":     p.get("tripleKills", 0),
                "quadraKills":     p.get("quadraKills", 0),
                "pentaKills":      p.get("pentaKills", 0),
            },
        })

    # Blue side first, then Red; within each team sort by kills desc
    canonical_players.sort(key=lambda p: (0 if p["team"] == "Blue" else 1, -p["kills"]))

    game_duration = info.get("gameDuration", 0)   # seconds in v5
    start_ms      = info.get("gameStartTimestamp", 0)
    if start_ms:
        ts = datetime.datetime.utcfromtimestamp(start_ms / 1000).isoformat() + "Z"
    else:
        ts = datetime.datetime.utcnow().isoformat() + "Z"

    numeric = "".join(filter(str.isdigit, riot_id))[:9]
    canonical_match_id = f"LOL{numeric}" if numeric else f"LOL{riot_id[:9]}"

    return {
        "schemaVersion": "1.0",
        "game":          "LoL",
        "matchId":       canonical_match_id,
        "riotMatchId":   riot_id,
        "players":       canonical_players,
        "result": {
            "teamBlue":      blue_kills,
            "teamRed":       red_kills,
            "winner":        winner,
            "gameDuration":  game_duration,
        },
        "timestamp": ts,
        "source": {
            "engine": "riot-api-v5",
        },
        "ocr": {
            "engine":         "riot-api",
            "confidence":     1.0,
            "reviewRequired": False,
        },
    }


class LoLRiotPipeline:
    """
    Full pipeline: two Riot IDs → canonical match JSON.

    player_a / player_b must be in "gameName#tagLine" format.
    If match_id is provided the history lookup is skipped entirely.
    queue defaults to 420 (Ranked Solo) — pass queue=None for all queues.
    """

    def run(
        self,
        player_a: str,
        player_b: str,
        match_id: str = None,
        queue: int = 420,
    ) -> tuple[dict, str]:
        """Returns (canonical_json, riot_match_id)."""
        if match_id:
            log.info("[riot-lol] Fetching match directly: %s", match_id)
            match = get_match(match_id)
            return parse_match_to_canonical(match), match_id

        def split_riot_id(riot_id: str):
            if "#" not in riot_id:
                raise ValueError(f"Riot ID must be gameName#tagLine, got: {riot_id!r}")
            name, tag = riot_id.rsplit("#", 1)
            return name.strip(), tag.strip()

        name_a, tag_a = split_riot_id(player_a)
        name_b, tag_b = split_riot_id(player_b)

        log.info("[riot-lol] Resolving PUUIDs: %s | %s", player_a, player_b)
        puuid_a = get_puuid(name_a, tag_a)
        puuid_b = get_puuid(name_b, tag_b)
        log.info("[riot-lol] PUUID A: %s...", puuid_a[:16])
        log.info("[riot-lol] PUUID B: %s...", puuid_b[:16])

        log.info("[riot-lol] Fetching match histories (queue=%s)", queue)
        history_a = get_match_history(puuid_a, count=20, queue=queue)
        history_b = get_match_history(puuid_b, count=20, queue=queue)

        set_b  = set(history_b)
        common = [m for m in history_a if m in set_b]

        if not common:
            raise RuntimeError(
                f"No common recent match found between {player_a} and {player_b}. "
                f"Checked last 20 games each (queue={queue}). "
                "Try queue=None to search all queues, or provide match_id directly."
            )

        match_id = common[0]
        log.info("[riot-lol] Common matchId: %s", match_id)

        match = get_match(match_id)
        return parse_match_to_canonical(match), match_id
