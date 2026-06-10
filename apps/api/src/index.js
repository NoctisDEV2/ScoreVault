'use strict';

require('dotenv').config();
const express = require('express');
const { pool } = require('./db');
const matchRoutes = require('./routes/matches');
const standingsRoutes = require('./routes/standings');

const { migrate } = require('./db');

const app = express();
app.use(express.json({ limit: '10mb' }));

// Health check
app.get('/health', (_req, res) => res.json({ ok: true }));

// Routes
app.use('/v1/matches', matchRoutes);
app.use('/v1/standings', standingsRoutes);

// Global error handler
app.use((err, _req, res, _next) => {
  console.error(err);
  res.status(err.status ?? 500).json({ error: err.message ?? 'Internal error' });
});

const PORT = process.env.PORT ?? 4000;
migrate()
  .then(() => app.listen(PORT, () => console.log(`[api] listening on :${PORT}`)))
  .catch(err => { console.error('[api] startup failed', err); process.exit(1); });

module.exports = app;
