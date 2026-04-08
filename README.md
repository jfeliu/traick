# traick

AI-powered WhatsApp assistant that tracks your personal projects, replies to contacts on your behalf, and sends proactive follow-up reminders.

## How it works

```
Incoming message → webhook → SQLite
                                 ↓ (immediately, background)
                           Claude claude-opus-4-6
                                 ↓
                      reply sent to contact
                                 ↓ (every 1 min)
                           Claude claude-opus-4-6
                                 ↓
                    projects / tasks / follow-ups
                                 ↓ (every 1 min)
                    reminder → contact via template
```

When a contact messages your business number, Claude reads the project context and conversation history, then replies automatically in the same language. In parallel, a background job extracts projects, action items, and deadlines. Proactive reminders are sent to each contact using a WhatsApp message template.

---

## Requirements

- Python 3.12+
- An [Anthropic API key](https://console.anthropic.com)
- A [Meta WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api) app (type: Business)
- A public HTTPS URL for the webhook (e.g. via [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/))

---

## Installation

```bash
git clone <repo>
cd traick

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e .
```

---

## Configuration

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Your Anthropic API key |
| `WHATSAPP_TOKEN` | ✅ | Meta Cloud API system user token |
| `WHATSAPP_PHONE_NUMBER_ID` | ✅ | Phone number ID from Meta dashboard |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | ✅ | WhatsApp Business Account ID from Meta dashboard |
| `WHATSAPP_VERIFY_TOKEN` | ✅ | Any random string — used to verify the webhook URL |
| `TO_PHONE_NUMBER` | ✅ | Fallback number for reminders (without `+`) |
| `ALLOWED_NUMBERS` | | Comma-separated list of numbers to track (without `+`). Leave empty to track all. |
| `DB_PATH` | | SQLite file path (default: `traick.db`) |
| `PROCESS_INTERVAL_MINUTES` | | How often to run extraction (default: `5`) |
| `REMINDER_INTERVAL_MINUTES` | | How often to check for due reminders (default: `15`) |

Phone numbers are stored and matched without `+` prefix (as Meta delivers them).

### Filtering contacts

Only messages from numbers in `ALLOWED_NUMBERS` are tracked. Messages from any other number are silently ignored. Each number's projects are stored separately.

```
ALLOWED_NUMBERS=15559876543,34612345678
```

Leave `ALLOWED_NUMBERS` unset to track messages from everyone.

---

## Meta WhatsApp Cloud API setup

1. Go to [developers.facebook.com](https://developers.facebook.com) and create an app (type: **Business**).
2. Add the **WhatsApp** product to your app.
3. Under *API Setup*, note your **Phone Number ID** and **WhatsApp Business Account ID**.
4. Create a **System User** in [business.facebook.com](https://business.facebook.com) → Settings → Users → System Users, generate a token with `whatsapp_business_messaging` and `whatsapp_business_management` permissions, and assign your WhatsApp Business Account as an asset with Full control.
5. Set up the webhook (next section) before saving.

### Connecting the webhook

Start the server and expose it with cloudflared:

```bash
# Terminal 1 — run the server
uvicorn traick.main:app --reload

# Terminal 2 — expose it
cloudflared tunnel --url http://localhost:8000
```

In the Meta dashboard under *Webhooks*:

- **Callback URL**: `https://<your-subdomain>.trycloudflare.com/webhook`
- **Verify token**: the value you set in `WHATSAPP_VERIFY_TOKEN`
- **Subscriptions**: check `messages`

Click **Verify and save**. The server will respond to Meta's verification request automatically.

### Creating the reminder template

Run this once to create the WhatsApp message template used for proactive reminders:

```bash
traick-setup
```

The template is submitted for Meta's approval automatically (usually approved within minutes).

---

## Seeding existing projects

To give traick context about projects that predate your WhatsApp conversations, write a plain-text description and run:

```bash
traick-seed projects.txt
```

Claude will extract projects, action items, and deadlines from the file and save them to the database, scoped to your `TO_PHONE_NUMBER`.

---

## Running

```bash
# Development (auto-reload on file changes)
uvicorn traick.main:app --reload

# Production
traick
# or: uvicorn traick.main:app --host 0.0.0.0 --port 8000
```

The server starts on port `8000`. Check it's up:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## Project structure

```
traick/
├── main.py              # FastAPI app + APScheduler startup
├── config.py            # Settings from .env
├── ai/
│   ├── client.py        # Anthropic client singleton
│   ├── extractor.py     # Structured project/task extraction
│   └── responder.py     # Conversational reply generation
├── db/
│   ├── database.py      # SQLite schema + init
│   └── repository.py    # CRUD for all tables
├── scheduler/
│   └── jobs.py          # Batch processing + reminder dispatch
├── webhook/
│   ├── router.py        # POST /webhook + GET /webhook (verification) + reply trigger
│   └── models.py        # Pydantic models for Meta webhook payloads
└── whatsapp/
    └── sender.py        # Meta Cloud API — free-form + template message sending
```

### Database tables

| Table | Description |
|---|---|
| `raw_messages` | Inbound messages, pending or processed |
| `projects` | Extracted projects, scoped to a phone number |
| `action_items` | Tasks and deadlines within a project |
| `follow_ups` | Scheduled reminder messages, sent to the project owner |

---

## Logs

The app logs to stdout. Key events:

```
INFO  traick.webhook.router   Saved message <id> from 15559876543
INFO  traick.ai.responder     Generated reply for 15559876543
INFO  traick.whatsapp.sender  Sent message to 15559876543
INFO  traick.scheduler.jobs   Processing 7 messages from 2 number(s)
INFO  traick.ai.extractor     Extracted 3 project updates from 7 messages (cache_read=1842)
INFO  traick.scheduler.jobs   Scheduled follow-up for 'Website redesign' in 3 days
INFO  traick.scheduler.jobs   Done — marked 7 messages as processed
INFO  traick.whatsapp.sender  Sent template message to 15559876543
```

`cache_read` in the extractor log shows how many tokens were served from Claude's prompt cache (saves ~90% on repeated calls).

---

## Admin UI

The admin interface is available at `/admin` when running the FastAPI app. It provides:
- Dashboard overview
- CRUD for Projects, Action Items, and Follow Ups
- Database table/row counts

### Usage

1. Start the app:
   ```bash
   uvicorn traick.main:app --reload
   ```
2. Open [http://localhost:8000/admin](http://localhost:8000/admin) in your browser.

### Features
- View, create, edit, and delete Projects
- Manage Action Items and Follow Ups
- Visualize database tables and row counts
