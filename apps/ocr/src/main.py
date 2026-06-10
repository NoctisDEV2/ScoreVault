"""
ScoreVault OCR Worker
Consumes jobs from the Redis 'ocr' BullMQ queue, runs per-game OCR pipelines,
and POSTs canonical JSON back to the Backend API.
"""

import os
import json
import time
import logging
import threading
import requests
import redis

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

logging.basicConfig(level=logging.INFO, format="[ocr] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="ScoreVault OCR Worker")


@app.get("/health")
def health():
    return {"ok": True}


# ── Redis / BullMQ queue consumer ────────────────────────────────────────────
# BullMQ stores jobs in Redis lists. The active queue key pattern is:
#   bull:{queueName}:wait  (jobs waiting to be processed)
# We use a simple BRPOPLPUSH loop to consume jobs atomically.

REDIS_URL  = os.getenv("REDIS_URL", "redis://localhost:6379")
API_URL    = os.getenv("API_URL", "http://api:4000")
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")

QUEUE_WAIT    = "bull:ocr:wait"
QUEUE_ACTIVE  = "bull:ocr:active"

_redis = redis.from_url(REDIS_URL, decode_responses=True)


def sign_body(body: dict) -> str:
    import hmac as _hmac
    import hashlib
    payload = json.dumps(body, separators=(",", ":"), sort_keys=False)
    sig = _hmac.new(INTERNAL_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def post_result(match_ref: str, canonical_json: dict, confidence: float, review_required: bool):
    """POST OCR result back to the Backend API."""
    body = {
        "canonicalJson": canonical_json,
        "confidence": confidence,
        "reviewRequired": review_required,
    }
    url = f"{API_URL}/v1/matches/{match_ref}/result"
    headers = {
        "Content-Type": "application/json",
        "X-Signature": sign_body(body),
    }
    resp = requests.post(url, json=body, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def process_job(job_data: dict):
    """
    Parse a BullMQ job payload and run the OCR pipeline.
    BullMQ job format: { id, name, data: { matchRef, imageUrl, game }, ... }
    """
    data = job_data.get("data", {})
    match_ref = data.get("matchRef")
    image_url = data.get("imageUrl")
    game      = data.get("game")

    if not all([match_ref, image_url, game]):
        log.warning("Malformed job, skipping: %s", job_data)
        return

    log.info("Processing matchRef=%s game=%s", match_ref, game)

    from pipelines.dispatcher import dispatch
    canonical_json, confidence, review_required = dispatch(game, image_url)

    result = post_result(match_ref, canonical_json, confidence, review_required)
    log.info("Submitted result for %s → %s", match_ref, result)


def worker_loop():
    """Blocking worker loop — runs in a background thread."""
    log.info("Worker started, listening on %s", QUEUE_WAIT)
    while True:
        try:
            # BRPOPLPUSH: atomically move one job from wait → active, blocking up to 5s
            raw = _redis.brpoplpush(QUEUE_WAIT, QUEUE_ACTIVE, timeout=5)
            if raw is None:
                continue  # timeout, loop again
            job_data = json.loads(raw)
            process_job(job_data)
            # Remove from active after successful processing
            _redis.lrem(QUEUE_ACTIVE, 1, raw)
        except Exception as exc:
            log.exception("Worker error: %s", exc)
            time.sleep(2)


# Start the worker thread when the FastAPI app starts
@app.on_event("startup")
def start_worker():
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()
    log.info("Worker thread started")
