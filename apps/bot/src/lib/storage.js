'use strict';

/**
 * Upload a screenshot to object storage and return the stored URL.
 *
 * In Phase 1 we use the Discord CDN URL directly (no S3 yet) — this keeps
 * Phase 1 self-contained. Phase 3 will wire in real S3/GCS upload here.
 *
 * @param {string} discordUrl  - Original Discord CDN URL
 * @param {string} filename    - Original filename
 * @param {string} userId      - Uploader's Discord ID
 * @returns {Promise<string>}  - URL to store in the DB and pass to OCR
 */
async function uploadScreenshot(discordUrl, filename, userId) {
  // TODO (Phase 3): upload to S3/GCS with a random key and return the object URL.
  // For now, return the Discord CDN URL directly. Discord CDN URLs expire after
  // ~24h; this is acceptable for Phase 1 / development.
  console.log(`[storage] using Discord CDN URL for user=${userId} file=${filename}`);
  return discordUrl;
}

module.exports = { uploadScreenshot };
