'use strict';

const Ajv2020 = require('ajv/dist/2020');
const addFormats = require('ajv-formats');
const crypto = require('crypto');
const schema = require('./match-1.0.json');

const ajv = new Ajv2020({ allErrors: true });
addFormats(ajv);
const _validate = ajv.compile(schema);

function validateMatch(obj) {
  const valid = _validate(obj);
  return { valid, errors: _validate.errors || null };
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value !== null && typeof value === 'object') {
    return Object.keys(value).sort().reduce(function(acc, k) {
      acc[k] = sortKeys(value[k]);
      return acc;
    }, {});
  }
  return value;
}

function canonicalize(obj) {
  return JSON.stringify(sortKeys(obj));
}

function hashMatch(obj) {
  var canonical = canonicalize(obj);
  try {
    var eth = require('ethers');
    return eth.keccak256(Buffer.from(canonical, 'utf8'));
  } catch (e) {
    return '0x' + crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
  }
}

module.exports = { validateMatch: validateMatch, canonicalize: canonicalize, hashMatch: hashMatch, schema: schema };
