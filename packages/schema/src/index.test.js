'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { validateMatch, canonicalize, hashMatch } = require('./index');

const validMatch = {
  schemaVersion: '1.0',
  game: 'Valorant',
  matchId: 'VAL12345',
  tournamentId: 'SCRIM-2026-Q2',
  players: [
    { name: 'AceHunter', team: 'A', kills: 20, deaths: 15, assists: 5, stats: { acs: 287 } }
  ],
  result: { teamA: 13, teamB: 11, winner: 'A' },
  timestamp: '2026-06-02T19:30:00Z',
  source: { discordId: '1029384756', channelId: '55667788' },
  ocr: { engine: 'tesseract-5', confidence: 0.94, reviewRequired: false }
};

describe('validateMatch', () => {
  it('accepts a valid match', () => {
    const { valid } = validateMatch(validMatch);
    assert.equal(valid, true);
  });

  it('rejects missing required fields', () => {
    const { valid, errors } = validateMatch({ schemaVersion: '1.0' });
    assert.equal(valid, false);
    assert.ok(errors.length > 0);
  });

  it('rejects unknown game', () => {
    const { valid } = validateMatch({ ...validMatch, game: 'Dota2' });
    assert.equal(valid, false);
  });

  it('rejects bad matchId pattern', () => {
    const { valid } = validateMatch({ ...validMatch, matchId: 'val123' });
    assert.equal(valid, false);
  });
});

describe('canonicalize', () => {
  it('sorts keys deterministically', () => {
    const a = canonicalize({ b: 1, a: 2 });
    const b = canonicalize({ a: 2, b: 1 });
    assert.equal(a, b);
  });

  it('produces no whitespace', () => {
    const s = canonicalize(validMatch);
    assert.ok(!s.includes('\n'));
    assert.ok(!s.includes('  '));
  });
});

describe('hashMatch', () => {
  it('returns a hex string', () => {
    const h = hashMatch(validMatch);
    assert.match(h, /^0x[0-9a-f]+$/);
  });

  it('is deterministic', () => {
    assert.equal(hashMatch(validMatch), hashMatch(validMatch));
  });
});
