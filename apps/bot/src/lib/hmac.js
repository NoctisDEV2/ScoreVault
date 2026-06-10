'use strict';

const crypto = require('crypto');

function signBody(body) {
  const secret = process.env.INTERNAL_SECRET ?? '';
  return 'sha256=' + crypto.createHmac('sha256', secret).update(JSON.stringify(body)).digest('hex');
}

module.exports = { signBody };
