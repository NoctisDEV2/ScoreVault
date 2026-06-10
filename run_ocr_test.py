"""
ScoreVault OCR / API test runner — outputs result to test.json

Modes:
  --riot   "PlayerA#TAG" "PlayerB#TAG"   Riot API (perfect accuracy, requires RIOT_API_KEY)
  --riot   "PlayerA#TAG" "PlayerB#TAG" "MATCH_ID"  Skip history lookup, fetch a specific match
  --easyocr  <image>  <game>             EasyOCR GPU (local fallback)
  (default)  <image>  <game>             Gemini Vision → EasyOCR fallback

Setup:
  pip install easyocr opencv-python-headless numpy Pillow
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
"""

import sys, json, os, logging
logging.basicConfig(level=logging.INFO, format="[ocr] %(message)s")

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


# ── Mode dispatch ─────────────────────────────────────────────────────────────

if '--riot' in sys.argv:
    # Usage: python run_ocr_test.py --riot "PlayerA#TAG" "PlayerB#TAG" [matchId]
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 2:
        print("Usage: python run_ocr_test.py --riot \"PlayerA#TAG\" \"PlayerB#TAG\" [matchId]")
        sys.exit(1)
    player_a = args[0]
    player_b = args[1]
    match_id = args[2] if len(args) > 2 else None

    print(f"[mode] Riot API")
    print(f"  Player A : {player_a}")
    print(f"  Player B : {player_b}")
    if match_id:
        print(f"  Match ID : {match_id}")

    from pipelines.riot_valorant import ValorantRiotPipeline
    pipeline = ValorantRiotPipeline()
    canonical, riot_match_id = pipeline.run(player_a, player_b, match_id=match_id)
    confidence     = 1.0
    review_required = False
    print(f"  Riot Match: {riot_match_id}")

else:
    # Screenshot-based modes
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 2:
        print("Usage: python run_ocr_test.py <image_path> <game> [--easyocr]")
        print("       python run_ocr_test.py --riot \"PlayerA#TAG\" \"PlayerB#TAG\" [matchId]")
        sys.exit(1)

    image_path    = args[0]
    game          = args[1]
    force_easyocr = '--easyocr' in sys.argv

    if force_easyocr:
        print("[mode] EasyOCR/GPU (forced)")
        from pipelines.valorant import ValorantPipeline
        from pipelines.cs2 import CS2Pipeline
        from pipelines.lol import LoLPipeline
        pipelines = {"Valorant": ValorantPipeline(), "CS2": CS2Pipeline(), "LoL": LoLPipeline()}
        canonical, confidence, review_required = pipelines[game].run(image_path)
    else:
        print("[mode] Gemini Vision (fallback: EasyOCR/GPU)")
        from pipelines.dispatcher import dispatch
        canonical, confidence, review_required = dispatch(game, image_path)


# ── Output ────────────────────────────────────────────────────────────────────

class SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, np.bool_):    return bool(obj)
            if isinstance(obj, np.integer):  return int(obj)
            if isinstance(obj, np.floating): return float(obj)
            if isinstance(obj, np.ndarray):  return obj.tolist()
        except ImportError:
            pass
        try:
            import torch
            if isinstance(obj, torch.Tensor): return obj.item()
        except ImportError:
            pass
        return super().default(obj)

output = {
    "confidence":       float(confidence),
    "review_required":  bool(review_required),
    "canonical":        canonical,
}

with open("test.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False, cls=SafeEncoder)

print(f"\nconfidence     : {float(confidence):.4f}")
print(f"review_required: {bool(review_required)}")
print(f"engine         : {canonical.get('ocr', {}).get('engine', '?')}")
print(f"players found  : {len(canonical.get('players', []))}")
result = canonical.get('result', {})
if result:
    w = result.get('winner', '?')
    td = result.get('teamDefender', result.get('teamA', '?'))
    ta = result.get('teamAttacker', result.get('teamB', '?'))
    print(f"result         : Defender {td} — Attacker {ta}  (winner: {w})")
print()
for p in canonical.get("players", []):
    acs = p.get("stats", {}).get("acs", "?")
    print(f"  [{p.get('team','?'):<10}]  {p['name']:<22}  K:{p['kills']:>2}  D:{p['deaths']:>2}  A:{p['assists']:>2}  ACS:{acs}")
print("\nFull output written to test.json")


# ── Debug mode (EasyOCR only) ─────────────────────────────────────────────────
if '--debug' in sys.argv and '--riot' not in sys.argv:
    print("\n── RAW EasyOCR detections (x_frac | text) ──")
    from pipelines.valorant import ValorantPipeline as _VP
    import cv2 as _cv2
    _vp = _VP()
    _img = _cv2.imread(image_path)
    _pre = _vp.preprocess(_img)
    _roi_w = _vp._roi_w
    _results = _vp.ocr_image(_pre)
    _sorted = sorted(_results, key=lambda r: r[0][0][1])
    _prev_y = None
    for _bbox, _text, _conf in _sorted:
        _y = (_bbox[0][1] + _bbox[2][1]) / 2
        _x = _bbox[0][0]
        _xf = _x / _roi_w
        _sep = "  |  " if _prev_y is None or abs(_y - _prev_y) <= 20 else "\n"
        print(f"{_sep}{_xf:.3f}:{_text}", end="")
        _prev_y = _y
    print()
