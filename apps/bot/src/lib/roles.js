'use strict';

/**
 * Check whether a guild member holds the active-subscriber role.
 * The role ID is configured via SUBSCRIBER_ROLE_ID env var.
 * Falls back to any role named "subscriber" (case-insensitive) if env not set.
 */
function hasSubscriberRole(member) {
  if (!member) return false;

  const roleId = process.env.SUBSCRIBER_ROLE_ID;
  if (roleId) {
    return member.roles.cache.has(roleId);
  }

  // Fallback: role name match
  return member.roles.cache.some(
    (r) => r.name.toLowerCase() === 'subscriber'
  );
}

module.exports = { hasSubscriberRole };
