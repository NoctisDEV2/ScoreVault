"""
OCR pipeline test — Valorant, val-test-01.png (Haven 13-3)

Run from repo root:
    pip install -r apps/ocr/requirements.txt --break-system-packages
    python -m pytest apps/ocr/tests/test_valorant_pipeline.py -v

The test image must be saved at:
    apps/ocr/tests/fixtures/val-test-01.png
"""

import json
import os
import sys
import pathlib
import pytest

# Make sure the src package is importable
SRC = pathlib.Path(__file__).parent.parent / "src"
sys.path.insert(0, str(SRC))

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
IMAGE_PATH = FIXTURES / "val-test-01.png"
GROUND_TRUTH_PATH = FIXTURES / "val-test-01-ground-truth.json"

with open(GROUND_TRUTH_PATH) as f:
    GT = json.load(f)


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_player(players, name):
    """Case-insensitive partial name match — tolerates minor OCR drift."""
    name_lower = name.lower()
    for p in players:
        if name_lower in p["name"].lower() or p["name"].lower() in name_lower:
            return p
    return None


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pipeline_output():
    """Run the full Valorant pipeline once; share result across all tests."""
    if not IMAGE_PATH.exists():
        pytest.skip(f"Test image not found: {IMAGE_PATH}\nSave val-test-01.png there and re-run.")

    from pipelines.valorant import ValorantPipeline
    canonical, confidence, review_required = ValorantPipeline().run(str(IMAGE_PATH))
    print(f"\n[pipeline] confidence={confidence:.4f}  review_required={review_required}")
    print(json.dumps(canonical, indent=2, ensure_ascii=False))
    return canonical, confidence, review_required


# ── Schema & top-level tests ──────────────────────────────────────────────────

def test_schema_version(pipeline_output):
    canonical, _, _ = pipeline_output
    assert canonical["schemaVersion"] == "1.0"

def test_game_field(pipeline_output):
    canonical, _, _ = pipeline_output
    assert canonical["game"] == "Valorant"

def test_player_count(pipeline_output):
    """Expect exactly 10 players (5v5)."""
    canonical, _, _ = pipeline_output
    assert len(canonical["players"]) == 10, (
        f"Expected 10 players, got {len(canonical['players'])}. "
        f"Players found: {[p['name'] for p in canonical['players']]}"
    )

def test_result_score(pipeline_output):
    canonical, _, _ = pipeline_output
    result = canonical.get("result", {})
    assert result.get("teamA") == 13, f"teamA score: expected 13, got {result.get('teamA')}"
    assert result.get("teamB") == 3,  f"teamB score: expected 3, got {result.get('teamB')}"
    assert result.get("winner") == "A"

def test_ocr_block_present(pipeline_output):
    canonical, _, _ = pipeline_output
    assert "ocr" in canonical
    assert 0.0 <= canonical["ocr"]["confidence"] <= 1.0

def test_confidence_acceptable(pipeline_output):
    """Warn (not fail) if confidence is low — still flag it."""
    _, confidence, _ = pipeline_output
    if confidence < 0.60:
        pytest.xfail(f"Low OCR confidence: {confidence:.4f} — parser may need tuning")


# ── Per-player stat tests ─────────────────────────────────────────────────────

@pytest.mark.parametrize("name,team,kills,deaths,assists,acs", [
    ("griffith",        "A", 21, 10, 11, 379),
    ("equanimity fan",  "A", 15, 10,  3, 260),
    ("Creeper",         "A", 12,  9,  9, 201),
    ("Jaegerjaquez",    "A", 12,  6,  6, 192),
    ("boofindaerec",    "B", 11,  7,  3, 192),
    ("MC Icenberg",     "B",  9, 12,  1, 160),
    ("Enoki Beef Rolls","B",  9, 17,  1, 149),
    ("TetoPear",        "B",  7, 14,  1, 137),
    ("Nytr0",           "B",  5, 15,  8, 123),
])
def test_player_stats(pipeline_output, name, team, kills, deaths, assists, acs):
    canonical, _, _ = pipeline_output
    player = find_player(canonical["players"], name)
    assert player is not None, f"Player '{name}' not found in output: {[p['name'] for p in canonical['players']]}"
    assert player["kills"]   == kills,   f"{name} kills:   expected {kills},   got {player['kills']}"
    assert player["deaths"]  == deaths,  f"{name} deaths:  expected {deaths},  got {player['deaths']}"
    assert player["assists"] == assists, f"{name} assists: expected {assists}, got {player['assists']}"
    assert player["stats"]["acs"] == acs, f"{name} ACS: expected {acs}, got {player['stats'].get('acs')}"

def test_sai_moon_player(pipeline_output):
    """
    Sai月 has a CJK character — OCR may mangle it.
    We accept any name containing 'Sai' and check stats.
    """
    canonical, _, _ = pipeline_output
    player = find_player(canonical["players"], "Sai")
    assert player is not None, "Player 'Sai月' (or 'Sai') not found"
    assert player["kills"]   == 12
    assert player["deaths"]  == 13
    assert player["assists"] == 3

def test_team_assignments(pipeline_output):
    """Top 5 rows should be team A, bottom 5 team B."""
    canonical, _, _ = pipeline_output
    players = canonical["players"]
    if len(players) == 10:
        team_a = [p for p in players if p.get("team") == "A"]
        team_b = [p for p in players if p.get("team") == "B"]
        assert len(team_a) == 5, f"Expected 5 team A players, got {len(team_a)}"
        assert len(team_b) == 5, f"Expected 5 team B players, got {len(team_b)}"
