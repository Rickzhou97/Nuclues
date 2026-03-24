# EClaw WhatsApp CRM Agent

Listens to a WhatsApp group, classifies messages with Claude AI, and logs CRM-relevant conversations to Ethos CRM automatically.

## How it works

```
WhatsApp Group
      │
      ▼
 whatsapp.js          ← connects to WhatsApp Web via wa-automate
      │  forwards every message
      ▼
  agent.py            ← Flask webhook server
      │  asks Claude to classify
      ▼
 Claude AI            ← decides: is this a lead / opportunity / complaint?
      │  if confidence ≥ 0.75
      ▼
 Ethos CRM            ← record is posted automatically
      │  reply sent back
      ▼
 WhatsApp Group       ← agent confirms action in chat
```

## Setup

### 1. Install dependencies

```bash
# Node (WhatsApp bridge)
cd nucleus-whatsapp-agent
npm install

# Build the local wa-automate library
cd ../wa-automate-nodejs
npm run build
cd ../nucleus-whatsapp-agent

# Python (CRM agent)
pip install anthropic requests flask python-dotenv
```

### 2. Configure `.env`

```env
ANTHROPIC_API_KEY=sk-ant-...
ETHOS_API_URL=https://your-ethos-instance.com/api/crm/records
ETHOS_API_KEY=your-ethos-api-key
WHATSAPP_GROUP_NAME=My Sales Team
CRM_THRESHOLD=0.75
AGENT_PORT=8000
```

### 3. Run

Open two terminals:

```bash
# Terminal 1 — WhatsApp bridge
node whatsapp.js

# Terminal 2 — CRM agent
python agent.py
```

On first run, a browser window will open — scan the QR code with WhatsApp on your phone (**Linked Devices → Link a Device**). The session is saved and future restarts won't need a QR scan.

## Behaviour

| Message type | Example | Action |
|---|---|---|
| Lead | "John from Acme wants a quote" | Logged to CRM + reply sent |
| Opportunity | "Sarah interested in enterprise plan" | Logged to CRM + reply sent |
| Deal | "Closed $10k deal with TechCorp" | Logged to CRM + reply sent |
| Complaint | "Client unhappy with delivery" | Logged to CRM + reply sent |
| Contact | "New contact: james@example.com" | Logged to CRM + reply sent |
| Casual | "sup", "good morning" | No action, no reply |

CRM threshold is configurable via `CRM_THRESHOLD` in `.env` (default: `0.75`).

## Ports

| Port | Service |
|---|---|
| `8000` | `agent.py` webhook (receives messages from `whatsapp.js`) |
| `8001` | `whatsapp.js` send server (receives outbound messages from `agent.py`) |

## Sending a message to the group programmatically

```bash
curl -X POST http://localhost:8001/send \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello from the bot!"}'
```

## Files

```
nucleus-whatsapp-agent/
├── whatsapp.js      # WhatsApp bridge — connects, listens, forwards, sends
├── agent.py         # CRM agent — classifies with Claude, posts to Ethos
├── .env             # Configuration (never commit this)
├── agent.log        # Auto-generated decision log
└── nucleus-crm.data.json  # Auto-generated WhatsApp session (never commit)
```
