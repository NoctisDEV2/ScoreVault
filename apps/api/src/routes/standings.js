'use strict';

const express = require('express');
const { pool } = require('../db');
const { requireHmac } = require('../middleware/hmac');

const router = express.Router();

// ── GET /v1/standings?game=Valorant&limit=20 ─────────────────────────────────
// Aggregates K/D/A from all verified matches for the given game.
// This is a Postgres-side aggregation over the JSONB payload.
// Phase 2 will layer in The Graph for on-chain verified data.
router.get('/', requireHmac, async (req, res, next) => {
  try {
    const { game, limit = 20 } = req.query;
    if (!game) return res.status(400).json({ error: 'game query param required' });

    const { rows } = await pool.query(
      `SELECT
         p->>'name'                        AS player,
         p->>'team'                        AS team,
         COUNT(*)::int                     AS matches_played,
         SUM((p->>'kills')::int)::int      AS total_kills,
         SUM((p->>'deaths')::int)::int     AS total_deaths,
         SUM((p->>'assists')::int)::int    AS total_assists
       FROM matches,
            jsonb_array_elements(payload->'players') AS p
       WHERE game = $1
         AND status = 'verified'
       GROUP BY p->>'name', p->>'team'
       ORDER BY total_kills DESC
       LIMIT $2`,
      [game, Math.min(Number(limit), 200)]
    );

    return res.json({ game, standings: rows });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
