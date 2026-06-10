'use strict';

require('dotenv').config();
const { Client, GatewayIntentBits, Events } = require('discord.js');
const handleUpload = require('./commands/upload');

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
});

client.once(Events.ClientReady, (c) => {
  console.log(`[bot] Ready as ${c.user.tag}`);
});

client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot) return;

  const content = message.content.trim();

  // Support both !upload and /upload prefix
  if (content.startsWith('!upload') || content.startsWith('/upload')) {
    await handleUpload(message);
  }
});

client.login(process.env.DISCORD_TOKEN);
