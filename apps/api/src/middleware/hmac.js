'use strict';

const crypto = require('crypto');

/**
 * HMAC service-to-service auth middleware.
 * Expects header: X-Signature: sha256=<hex>
 * Signature is HMAC-SHA256 of the raw request body using INTERNAL_SECRET.
 */
function requireHmac(req, res, next) {
  const sig = req.headers['x-signature'];
  if (!sig) return res.status(401).json({ error: 'Missing X-Signature' });

  const secret = process.env.INTERNAL_SECRET;
  if (!secret) {
    console.warn('[hmac] INTERNAL_SECRET not set — skipping HMAC check in dev');
    return next();
  }

  const body = JSON.stringify(req.body);
  const expected = 'sha256=' + crypto.createHmac('sha256', secret).update(body).digest('hex');

  const sigBuf      = Buffer.from(sig);
  const expectedBuf = Buffer.from(expected);
  if (sigBuf.length !== expectedBuf.length || !crypto.timingSafeEqual(sigBuf, expectedBuf)) {
    return res.status(401).json({ error: 'Invalid signature' });
  }
  next();
}

/**
 * Sign a request body for outgoing service-to-service calls.
 * @param {object} body
 * @returns {string} header value
 */
function signBody(body) {
  const secret = process.env.INTERNAL_SECRET ?? '';
  return 'sha256=' + crypto.createHmac('sha256', secret).update(JSON.stringify(body)).digest('hex');
}

module.exports = { requireHmac, signBody };
