'use strict';

const express = require('express');
const { v4: uuidv4 } = require('uuid');
const { pool } = require('../db');
const { enqueueOcrJob } = require('../queue');
const { validateMatch } = require('@scorevault/schema');
const { requireHmac } = require('../middleware/hmac');

const router = express.Router();

// ── POST /v1/matches/intake ──────────────────────────────────────────────────
// Called by the Discord bot after uploading a screenshot.
// Body: { discordId, channelId, game, imageUrl }
router.post('/intake', requireHmac, async (req, res, next) => {
  try {
    const { discordId, channelId, game, imageUrl } = req.body;
    if (!discordId || !game || !imageUrl) {
      return res.status(400).json({ error: 'discordId, game, imageUrl required' });
    }

    const ALLOWED_GAMES = ['Valorant', 'CS2', 'LoL'];
    if (!ALLOWED_GAMES.includes(game)) {
      return res.status(400).json({ error: `game must be one of: ${ALLOWED_GAMES.join(', ')}` });
    }

    const matchRef = uuidv4();
    await pool.query(
      `INSERT INTO matches (id, game, status, discord_id, channel_id, image_url)
       VALUES ($1, $2, 'processing', $3, $4, $5)`,
      [matchRef, game, discordId, channelId ?? null, imageUrl]
    );

    await enqueueOcrJob({ matchRef, imageUrl, game });

    return res.status(202).json({ matchRef });
  } catch (err) {
    next(err);
  }
});

// ── POST /v1/matches/:ref/result ─────────────────────────────────────────────
// Called by the OCR worker with the parsed canonical JSON.
// Body: { canonicalJson, confidence, reviewRequired }
router.post('/:ref/result', requireHmac, async (req, res, next) => {
  try {
    const { ref } = req.params;
    const { canonicalJson, confidence, reviewRequired } = req.body;

    if (!canonicalJson) return res.status(400).json({ error: 'canonicalJson required' });

    // Validate the canonical JSON against the schema
    const { valid, errors } = validateMatch(canonicalJson);
    if (!valid) {
      return res.status(422).json({ accepted: false, schemaValid: false, errors });
    }

    const status = reviewRequired ? 'review_required' : 'pending';
    await pool.query(
      `UPDATE matches
       SET payload = $1, confidence = $2, review_required = $3,
           status = $4, updated_at = NOW()
       WHERE id = $5`,
      [JSON.stringify(canonicalJson), confidence ?? null, reviewRequired ?? false, status, ref]
    );

    // TODO (Phase 3): emit webhook to bot that match is ready

    return res.json({ accepted: true, schemaValid: true, status });
  } catch (err) {
    next(err);
  }
});

// ── GET /v1/matches ──────────────────────────────────────────────────────────
// Returns matches filtered by status (e.g. ?status=pending).
router.get('/', requireHmac, async (req, res, next) => {
  try {
    const { status, limit = 50 } = req.query;
    const params = [];
    let where = '';
    if (status) {
      params.push(status);
      where = `WHERE status = $1`;
    }
    params.push(Math.min(Number(limit), 200));
    const { rows } = await pool.query(
      `SELECT id, match_id, game, status, confidence, review_required, created_at, updated_at
       FROM matches ${where}
       ORDER BY created_at DESC
       LIMIT $${params.length}`,
      params
    );
    return res.json({ matches: rows });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
