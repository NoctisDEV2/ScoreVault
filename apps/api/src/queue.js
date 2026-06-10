'use strict';

const { Queue } = require('bullmq');
const IORedis = require('ioredis');

const connection = new IORedis(process.env.REDIS_URL ?? 'redis://localhost:6379', {
  maxRetriesPerRequest: null,
});

const ocrQueue = new Queue('ocr', { connection });

/**
 * Enqueue an OCR job.
 * @param {{ matchRef: string, imageUrl: string, game: string }} data
 */
async function enqueueOcrJob(data) {
  await ocrQueue.add('process', data, {
    attempts: 3,
    backoff: { type: 'exponential', delay: 2000 },
  });
}

module.exports = { ocrQueue, enqueueOcrJob };
