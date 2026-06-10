"""
Riot Games API client for ScoreVault.

Covers:
  - Account v1  : PUUID lookup by Riot ID (gameName#tagLine)
  - Val Match v1 : match history by PUUID
  - Val Match v1 : match details by matchId

Requires:
  RIOT_API_KEY  — from https://developer.riotgames.com
  RIOT_REGION   — routing region, e.g. "ap", "na", "eu", "kr"  (default: "ap")
  RIOT_PLATFORM — platform cluster, e.g. "na1", "ap1", "eu1"  (default: "ap")

Riot routing:
  Account API  → regional cluster  e.g. https://asia.api.riotgames.com
  Val Match API → platform cluster  e.g. https://ap.api.riotgames.com
"""

import json
import logging
import os
import urllib.request
import urllib.error
import urllib.parse

log = logging.getLogger(__name__)

# Regional routing for Account API
ACCOUNT_HOSTS = {
    "na":  "americas.api.riotgames.com",
    "na1": "americas.api.riotgames.com",
    "br":  "americas.api.riotgames.com",
    "latam": "americas.api.riotgames.com",
    "eu":  "europe.api.riotgames.com",
    "euw1": "europe.api.riotgames.com",
    "eun1": "europe.api.riotgames.com",
    "kr":  "asia.api.riotgames.com",
    "ap":  "asia.api.riotgames.com",
    "sea": "sea.api.riotgames.com",
}

# Platform routing for Val Match API
PLATFORM_HOSTS = {
    "na":  "na.api.riotgames.com",
    "na1": "na.api.riotgames.com",
    "br1": "br.api.riotgames.com",
    "latam": "latam.api.riotgames.com",
    "eu":  "eu.api.riotgames.com",
    "euw1": "eu.api.riotgames.com",
    "eun1": "eu.api.riotgames.com",
    "kr":  "kr.api.riotgames.com",
    "ap":  "ap.api.riotgames.com",
    "sea": "sea.api.riotgames.com",
}


class RiotAPIError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(f"Riot API {status}: {message}")


class RiotClient:

    def __init__(self):
        self.api_key = os.getenv("RIOT_API_KEY", "")
        region = os.getenv("RIOT_REGION", "ap").lower()
        platform = os.getenv("RIOT_PLATFORM", region).lower()

        self._account_host = ACCOUNT_HOSTS.get(region, f"{region}.api.riotgames.com")
        self._platform_host = PLATFORM_HOSTS.get(platform, f"{platform}.api.riotgames.com")

        log.info("[riot] account_host=%s  platform_host=%s", self._account_host, self._platform_host)

    def _get(self, host, path):
        if not self.api_key:
            raise RiotAPIError(0, "RIOT_API_KEY not set")
        url = f"https://{host}{path}"
        req = urllib.request.Request(
            url,
            headers={
                "X-Riot-Token": self.api_key,
                "Accept": "application/json",
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RiotAPIError(e.code, body)

    # ── Account API ───────────────────────────────────────────────────────────

    def get_account_by_riot_id(self, game_name: str, tag_line: str) -> dict:
        """
        Returns { puuid, gameName, tagLine }.
        Riot ID format: gameName#tagLine  e.g. "PlayerOne#1234"
        """
        path = (
            f"/riot/account/v1/accounts/by-riot-id/"
            f"{urllib.parse.quote(game_name)}/{urllib.parse.quote(tag_line)}"
        )
        return self._get(self._account_host, path)

    def parse_riot_id(self, riot_id: str) -> tuple[str, str]:
        """Split 'PlayerOne#NA1' into ('PlayerOne', 'NA1')."""
        if "#" not in riot_id:
            raise ValueError(f"Invalid Riot ID (expected gameName#tagLine): {riot_id!r}")
        game_name, tag_line = riot_id.rsplit("#", 1)
        return game_name.strip(), tag_line.strip()

    def get_puuid(self, riot_id: str) -> str:
        """Convenience: return PUUID for a Riot ID string."""
        game_name, tag_line = self.parse_riot_id(riot_id)
        account = self.get_account_by_riot_id(game_name, tag_line)
        return account["puuid"]

    # ── Val Match API ─────────────────────────────────────────────────────────

    def get_match_history(self, puuid: str, count: int = 20) -> list[str]:
        """
        Returns a list of matchIds (most recent first) for a given PUUID.
        count: number of matches to fetch (max 20 per Riot free tier).
        """
        path = f"/val/match/v1/matchlists/by-puuid/{urllib.parse.quote(puuid)}"
        data = self._get(self._platform_host, path)
        history = data.get("history", [])
        # Each entry: { matchId, gameStartTimeMillis, teamId }
        # Sort by most recent first
        history.sort(key=lambda m: m.get("gameStartTimeMillis", 0), reverse=True)
        return [m["matchId"] for m in history[:count]]

    def get_match(self, match_id: str) -> dict:
        """
        Returns full match detail object from Riot API.
        """
        path = f"/val/match/v1/matches/{urllib.parse.quote(match_id)}"
        return self._get(self._platform_host, path)
