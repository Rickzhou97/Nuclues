/**
 * whatsapp.js — NUCLEUS CRM bridge
 * Listens to ALL WhatsApp groups and acts when the bot is @mentioned.
 * Forwards the message to agent.py on port 8000.
 * Exposes POST /send?groupId=<id> to send replies back.
 */

require('dotenv').config();
const { create } = require('../wa-automate-nodejs');
const axios = require('axios');
const http = require('http');

const WEBHOOK_URL = 'http://localhost:8000/webhook';
const SEND_PORT   = 8001;

// Track messages sent by the bot so we don't loop on our own replies
const botSentMessages = new Set();

let botNumber = null; // set after client connects

async function start(client) {
  botNumber = await client.getHostNumber();
  console.log(`[INFO] NUCLEUS CRM Agent connected as ${botNumber}`);
  console.log(`[INFO] Listening in ALL groups — @mention to activate`);

  // --- Outbound HTTP server on port 8001 ---
  // agent.py POSTs { "chatId": "...", "message": "..." }
  const server = http.createServer(async (req, res) => {
    if (req.method === 'POST' && req.url === '/send') {
      let body = '';
      req.on('data', chunk => body += chunk);
      req.on('end', async () => {
        try {
          const { chatId, message } = JSON.parse(body);
          botSentMessages.add(message);
          await client.sendText(chatId, message);
          console.log(`[SEND] → ${chatId}: ${message}`);
          res.writeHead(200);
          res.end(JSON.stringify({ ok: true }));
        } catch (err) {
          console.error('[ERROR] Send failed:', err.message);
          res.writeHead(500);
          res.end(JSON.stringify({ error: err.message }));
        }
      });
    } else {
      res.writeHead(404);
      res.end();
    }
  });
  server.listen(SEND_PORT, () => {
    console.log(`[INFO] Send server listening on port ${SEND_PORT}`);
  });

  // --- Inbound message listener ---
  client.onAnyMessage(async (message) => {
    try {
      if (!message.isGroupMsg) return;

      // Ignore the bot's own replies
      if (botSentMessages.has(message.body)) {
        botSentMessages.delete(message.body);
        return;
      }

      const body = message.body || '';

      // Check if the bot is @mentioned by number or by name (@Nucleus)
      const mentioned = message.mentionedJidList || [];
      const botJid = `${botNumber}@c.us`;
      const isMentioned = mentioned.includes(botJid)
        || body.includes(`@${botNumber}`)
        || /\@nucleus/i.test(body);

      if (!isMentioned) return;

      const chat = await client.getChatById(message.chatId);
      const chatName = chat?.name || message.chatId;

      // Strip the @mention from the body before forwarding
      const cleanBody = body
        .replace(new RegExp(`@${botNumber}`, 'g'), '')
        .replace(/@nucleus/gi, '')
        .trim();

      const payload = {
        sender:    message.sender?.pushname || message.from,
        group:     chatName,
        chatId:    message.chatId,
        body:      cleanBody,
        timestamp: message.t,
        messageId: message.id,
      };

      console.log(`[MSG] [${chatName}] ${payload.sender}: ${cleanBody}`);

      await axios.post(WEBHOOK_URL, payload, {
        timeout: 10000,
        headers: { 'Content-Type': 'application/json' },
      });

    } catch (err) {
      console.error('[ERROR] Failed to forward message:', err.message);
    }
  });
}

create({
  sessionId:      'nucleus-crm',
  headless:       false,
  qrTimeout:      0,
  authTimeout:    60,
  killProcessOnBrowserClose: true,
  logConsole:     false,
  disableSpins:   true,
}).then(start).catch((err) => {
  console.error('[FATAL] Could not create WhatsApp client:', err.message);
  process.exit(1);
});
