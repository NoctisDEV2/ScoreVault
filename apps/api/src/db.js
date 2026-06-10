'use strict';

const { Pool } = require('pg');

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

/**
 * Run the migration to create the matches table if it doesn't exist.
 */
async function migrate() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS matches (
      id            UUID PRIMARY KEY,
      match_id      TEXT UNIQUE,
      game          TEXT NOT NULL,
      status        TEXT NOT NULL DEFAULT 'processing',
      -- 'processing' | 'pending' | 'verified' | 'review_required'
      payload       JSONB,
      confidence    NUMERIC(5,4),
      review_required BOOLEAN DEFAULT FALSE,
      discord_id    TEXT,
      channel_id    TEXT,
      image_url     TEXT,
      tx_hash       TEXT,
      ipfs_cid      TEXT,
      created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS audit_log (
      id         BIGSERIAL PRIMARY KEY,
      match_ref  UUID REFERENCES matches(id),
      actor      TEXT NOT NULL,
      action     TEXT NOT NULL,
      before     JSONB,
      after      JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
  `);
  console.log('[db] migrations complete');
}

module.exports = { pool, migrate };
