"""
Riot API match data test runner — outputs result to test.json

Usage:
    python run_riot_test.py "PlayerOne#NA1" "PlayerTwo#NA1"
    python run_riot_test.py "PlayerOne#NA1" "PlayerTwo#NA1" --match-id <matchId>

Requires RIOT_API_KEY in .env
"""

import sys, json, os, logging
logging.basicConfig(level=logging.INFO, format="[riot] %(message)s")

# Load .env
env_file = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'apps', 'ocr', 'src'))

if len(sys.argv) < 3:
    print("Usage: python run_riot_test.py <RiotID_A> <RiotID_B> [--match-id <id>]")
    print("  RiotID format: gameName#tagLine  e.g. griffith#1234")
    sys.exit(1)

riot_id_a = sys.argv[1]
riot_id_b = sys.argv[2]

# Optional: pass a specific match ID directly
match_id = None
if '--match-id' in sys.argv:
    idx = sys.argv.index('--match-id')
    match_id = sys.argv[idx + 1]

from pipelines.riot_valorant import ValorantRiotPipeline
from riot_client import RiotAPIError

try:
    pipeline = ValorantRiotPipeline()
    canonical, used_match_id = pipeline.run(riot_id_a, riot_id_b, match_id=match_id)
except RiotAPIError as e:
    print(f"\n[error] Riot API error {e.status}: {e}")
    if e.status == 403:
        print("  → API key invalid or expired. Get a new key at https://developer.riotgames.com")
    elif e.status == 404:
        print("  → Player not found. Check the Riot ID (gameName#tagLine) and region.")
    elif e.status == 429:
        print("  → Rate limit hit. Wait 2 minutes and try again.")
    sys.exit(1)

with open("test.json", "w", encoding="utf-8") as f:
    json.dump({"match_id": used_match_id, "canonical": canonical}, f, indent=2, ensure_ascii=False)

print(f"\nmatch_id  : {used_match_id}")
print(f"map       : {canonical.get('map', '?')}")
print(f"mode      : {canonical.get('mode', '?')}")
print(f"result    : Defender {canonical['result']['teamDefender']} – Attacker {canonical['result']['teamAttacker']}  (winner: {canonical['result']['winner']})")
print(f"players   : {len(canonical.get('players', []))}")
print()
for p in canonical.get("players", []):
    acs = p.get("stats", {}).get("acs", "?")
    print(f"  [{p.get('team','?'):<10}]  {p['name']:<22}  K:{p['kills']:>2}  D:{p['deaths']:>2}  A:{p['assists']:>2}  ACS:{acs}")
print("\nFull output written to test.json")
