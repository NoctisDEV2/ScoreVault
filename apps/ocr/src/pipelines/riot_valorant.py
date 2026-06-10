"""
Valorant Riot API pipeline.

Flow:
  1. Resolve Riot ID (gameName#tagLine) → PUUID for both players
  2. Fetch match history for each player (list of matchIds)
  3. Find most recent common matchId
  4. Fetch full match data from Riot API
  5. Map to canonical JSON schema

Requires: RIOT_API_KEY and RIOT_REGION in .env
"""

import os
import json
import logging
import datetime
import urllib.request
import urllib.error
import urllib.parse

log = logging.getLogger(__name__)

# Valorant API regional routing
# Valid values: americas, europe, asia, esports
RIOT_REGION  = os.getenv("RIOT_REGION", "americas")
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "")

BASE = f"https://{RIOT_REGION}.api.riotgames.com"


def _get(path: str) -> dict:
    """Make an authenticated GET request to the Riot API."""
    if not RIOT_API_KEY:
        raise RuntimeError("RIOT_API_KEY not set in environment")
    url = BASE + path
    req = urllib.request.Request(
        url,
        headers={
            "X-Riot-Token": RIOT_API_KEY,
            "Accept": "application/json",
        }
    )
    log.debug("[riot] GET %s", url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Riot API {e.code} on {path}: {body}") from e


def get_puuid(game_name: str, tag_line: str) -> str:
    """Resolve gameName#tagLine to PUUID."""
    name_enc = urllib.parse.quote(game_name)
    tag_enc  = urllib.parse.quote(tag_line)
    data = _get(f"/riot/account/v1/accounts/by-riot-id/{name_enc}/{tag_enc}")
    return data["puuid"]


def get_match_history(puuid: str, size: int = 20) -> list[str]:
    """Return the most recent `size` matchIds for a PUUID."""
    data = _get(f"/val/match/v1/matchlists/by-puuid/{puuid}")
    # Response: { puuid, history: [ { matchId, gameStartTimeMillis, queueId } ] }
    history = data.get("history", [])
    # Sort most-recent first (by gameStartTimeMillis)
    history.sort(key=lambda m: m.get("gameStartTimeMillis", 0), reverse=True)
    return [m["matchId"] for m in history[:size]]


def get_match(match_id: str) -> dict:
    """Fetch full match data by matchId."""
    return _get(f"/val/match/v1/matches/{match_id}")


def parse_match_to_canonical(match: dict) -> dict:
    """
    Map Riot match JSON → ScoreVault canonical schema.

    Riot team IDs: "Blue" (Defender) and "Red" (Attacker) per Riot convention.
    We map Blue → "Defender", Red → "Attacker".
    """
    info     = match.get("matchInfo", {})
    players  = match.get("players", [])
    teams    = match.get("teams", [])

    match_id = info.get("matchId", "")
    # Strip region prefix if present, e.g. "NA1_..." → keep as-is
    short_id = match_id.split("_")[-1] if "_" in match_id else match_id

    # Build team results
    team_map = {t["teamId"]: t for t in teams}
    blue = team_map.get("Blue", {})
    red  = team_map.get("Red", {})

    blue_rounds = blue.get("roundsWon", 0)
    red_rounds  = red.get("roundsWon", 0)
    winner = "Defender" if blue.get("won") else "Attacker"

    canonical_players = []
    for p in players:
        team_id = p.get("teamId", "")
        team    = "Defender" if team_id == "Blue" else "Attacker"
        stats   = p.get("stats", {})
        name    = p.get("gameName", p.get("puuid", "unknown"))

        canonical_players.append({
            "name":    name,
            "team":    team,
            "kills":   stats.get("kills", 0),
            "deaths":  stats.get("deaths", 0),
            "assists": stats.get("assists", 0),
            "stats": {
                "acs":         round(stats.get("score", 0) / max(info.get("roundsPlayed", 1), 1)),
                "adr":         0,   # not in match/v1 endpoint
                "firstBloods": 0,   # not in match/v1 endpoint
            },
        })

    # Sort: Defenders first, then Attackers; within each team sort by kills desc
    canonical_players.sort(key=lambda p: (0 if p["team"] == "Defender" else 1, -p["kills"]))

    # Timestamp from match start
    start_ms = info.get("gameStartMillis", 0)
    if start_ms:
        ts = datetime.datetime.utcfromtimestamp(start_ms / 1000).isoformat() + "Z"
    else:
        ts = datetime.datetime.utcnow().isoformat() + "Z"

    # Build a VAL-prefixed matchId from the numeric part
    numeric = "".join(filter(str.isdigit, short_id))[:9]
    canonical_match_id = f"VAL{numeric}" if numeric else f"VAL{short_id[:9]}"

    return {
        "schemaVersion": "1.0",
        "game":          "Valorant",
        "matchId":       canonical_match_id,
        "riotMatchId":   match_id,
        "players":       canonical_players,
        "result": {
            "teamDefender": blue_rounds,
            "teamAttacker": red_rounds,
            "winner":       winner,
        },
        "timestamp": ts,
        "source": {
            "engine": "riot-api-v1",
        },
        "ocr": {
            "engine":         "riot-api",
            "confidence":     1.0,
            "reviewRequired": False,
        },
    }


class ValorantRiotPipeline:
    """
    Full pipeline: two Riot IDs → canonical match JSON.
    """

    def run(
        self,
        player_a: str,   # "gameName#tagLine"
        player_b: str,   # "gameName#tagLine"
        match_id: str = None,  # if provided, skip history lookup
    ) -> tuple[dict, str]:
        """
        Returns (canonical_json, riot_match_id).
        If match_id is provided, fetches that match directly.
        Otherwise finds the most recent common match between player_a and player_b.
        """
        if match_id:
            log.info("[riot] Fetching match directly: %s", match_id)
            match = get_match(match_id)
            return parse_match_to_canonical(match), match_id

        # Parse Riot IDs
        def split_riot_id(riot_id: str):
            if "#" not in riot_id:
                raise ValueError(f"Riot ID must be in gameName#tagLine format, got: {riot_id!r}")
            name, tag = riot_id.rsplit("#", 1)
            return name.strip(), tag.strip()

        name_a, tag_a = split_riot_id(player_a)
        name_b, tag_b = split_riot_id(player_b)

        log.info("[riot] Resolving PUUIDs for %s and %s", player_a, player_b)
        puuid_a = get_puuid(name_a, tag_a)
        puuid_b = get_puuid(name_b, tag_b)
        log.info("[riot] PUUID A: %s", puuid_a[:16] + "...")
        log.info("[riot] PUUID B: %s", puuid_b[:16] + "...")

        log.info("[riot] Fetching match histories")
        history_a = get_match_history(puuid_a, size=20)
        history_b = get_match_history(puuid_b, size=20)

        # Find most recent common match
        set_b = set(history_b)
        common = [m for m in history_a if m in set_b]
        if not common:
            raise RuntimeError(
                f"No common recent match found between {player_a} and {player_b}. "
                "Check that both players played together in the last 20 games."
            )

        match_id = common[0]
        log.info("[riot] Found common matchId: %s", match_id)

        match = get_match(match_id)
        return parse_match_to_canonical(match), match_id
