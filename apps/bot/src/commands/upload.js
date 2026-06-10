'use strict';

const fetch = (...args) => import('node-fetch').then(({ default: f }) => f(...args));
const { signBody } = require('../lib/hmac');
const { hasSubscriberRole } = require('../lib/roles');
const { uploadScreenshot } = require('../lib/storage');
const { EmbedBuilder } = require('discord.js');

// Map channel names / IDs to game slugs. Admins can configure this via
// CHANNEL_GAME_MAP env var: "channelId:Game,channelId2:Game2"
function buildChannelGameMap() {
  const raw = process.env.CHANNEL_GAME_MAP ?? '';
  const map = {};
  for (const pair of raw.split(',')) {
    const [id, game] = pair.split(':');
    if (id && game) map[id.trim()] = game.trim();
  }
  return map;
}

const VALID_GAMES = ['Valorant', 'CS2', 'LoL'];

/**
 * Parse the game from the message.
 * Priority: explicit `game:Valorant` arg > channel map > error.
 */
function resolveGame(message) {
  const channelMap = buildChannelGameMap();

  // Explicit arg: !upload game:CS2
  const match = message.content.match(/\bgame:(\w+)\b/i);
  if (match) {
    const g = match[1];
    // Normalize casing
    const found = VALID_GAMES.find(v => v.toLowerCase() === g.toLowerCase());
    return found ?? null;
  }

  // Channel mapping
  if (channelMap[message.channelId]) return channelMap[message.channelId];

  return null;
}

/**
 * Handle the !upload command.
 * 1. Check subscriber role
 * 2. Validate attachment
 * 3. Upload screenshot to object storage
 * 4. Call /v1/matches/intake
 * 5. Reply with embed
 */
async function handleUpload(message) {
  // 1. Check subscriber role
  if (!hasSubscriberRole(message.member)) {
    return message.reply({
      content: '❌ You need an active ScoreVault subscription to upload match results.',
      allowedMentions: { repliedUser: false },
    });
  }

  // 2. Validate attachment
  const attachment = message.attachments.first();
  if (!attachment) {
    return message.reply({
      content: '❌ Please attach a screenshot. Usage: `!upload game:Valorant` (with image attached)',
      allowedMentions: { repliedUser: false },
    });
  }

  const isImage = attachment.contentType?.startsWith('image/');
  if (!isImage) {
    return message.reply({ content: '❌ Attachment must be an image.', allowedMentions: { repliedUser: false } });
  }

  if (attachment.size > 10 * 1024 * 1024) {
    return message.reply({ content: '❌ Image too large (max 10 MB).', allowedMentions: { repliedUser: false } });
  }

  // 3. Resolve game
  const game = resolveGame(message);
  if (!game) {
    return message.reply({
      content: `❌ Could not determine game. Use \`game:Valorant\`, \`game:CS2\`, or \`game:LoL\`. Valid: ${VALID_GAMES.join(', ')}`,
      allowedMentions: { repliedUser: false },
    });
  }

  // Send a processing reply immediately (async flow)
  const processingEmbed = new EmbedBuilder()
    .setColor(0x5865f2)
    .setTitle(`⏳ Processing your ${game} match…`)
    .setDescription('Your screenshot is being analyzed. We'll update you when it's ready for review.')
    .setFooter({ text: 'ScoreVault • Match Ingestion' })
    .setTimestamp();

  const reply = await message.reply({ embeds: [processingEmbed], allowedMentions: { repliedUser: false } });

  try {
    // 4. Upload screenshot to object storage (or use Discord CDN URL directly)
    const imageUrl = await uploadScreenshot(attachment.url, attachment.name, message.author.id);

    // 5. Call /v1/matches/intake
    const body = {
      discordId: message.author.id,
      channelId: message.channelId,
      game,
      imageUrl,
    };

    const apiUrl = `${process.env.API_URL ?? 'http://api:4000'}/v1/matches/intake`;
    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Signature': signBody(body),
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`API error ${response.status}: ${err}`);
    }

    const { matchRef } = await response.json();

    // Update the reply embed with the match ref
    const confirmedEmbed = new EmbedBuilder()
      .setColor(0x57f287)
      .setTitle(`✅ ${game} match queued`)
      .addFields(
        { name: 'Match Ref', value: `\`${matchRef}\``, inline: true },
        { name: 'Status',    value: 'Processing',       inline: true },
      )
      .setDescription('OCR is running. You'll receive a notification once the stats are ready for verification.')
      .setFooter({ text: 'ScoreVault • Match Ingestion' })
      .setTimestamp();

    await reply.edit({ embeds: [confirmedEmbed] });
  } catch (err) {
    console.error('[bot] upload error', err);
    const errorEmbed = new EmbedBuilder()
      .setColor(0xed4245)
      .setTitle('❌ Upload failed')
      .setDescription(`An error occurred: ${err.message}`)
      .setFooter({ text: 'ScoreVault • Match Ingestion' })
      .setTimestamp();
    await reply.edit({ embeds: [errorEmbed] });
  }
}

module.exports = handleUpload;
