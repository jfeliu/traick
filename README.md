# traick

AI-powered WhatsApp assistant that tracks your personal projects, replies to contacts on your behalf, and sends proactive follow-up reminders.

## How it works

```
Incoming message → webhook → SQLite
                                 ↓ (immediately, background)
                           local AI model (Ollama)
                                 ↓
                      reply sent to contact
                                 ↓ (every 1 min)
                           local AI model (Ollama)
                                 ↓
                    projects / tasks / follow-ups
                                 ↓ (every 1 min)
                    reminder → contact via template
```

When a contact messages your business number, the AI reads the project context and conversation history, then replies automatically in the same language. In parallel, a background job extracts projects, action items, and deadlines. Proactive reminders are sent to each contact using a WhatsApp message template.

---

## Requirements

- Python 3.12+
- [Ollama](https://ollama.ai) running locally
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

## Ollama setup

### Installation

```bash
# Linux/macOS
curl -fsSL https://ollama.ai/install.sh | sh
```

### Choosing a model

Any Ollama model that supports JSON mode works. Recommendations based on available VRAM:

| VRAM | Model | Command |
|---|---|---|
| 4 GB | `qwen2.5:7b` | `ollama pull qwen2.5:7b` |
| 8 GB | `qwen2.5:14b` | `ollama pull qwen2.5:14b` |
| 16 GB | `qwen2.5:14b` | `ollama pull qwen2.5:14b` |
| 24 GB+ | `qwen2.5:32b` | `ollama pull qwen2.5:32b` |

`qwen2.5:14b` is the recommended default — strong instruction following and structured JSON output (critical for the extractor). Set your choice in `.env` via `AI_MODEL`.

### Using a custom model (GGUF)

If you have a GGUF file (e.g. downloaded from HuggingFace):

```bash
# Create a Modelfile next to the .gguf file
cat > Modelfile << 'EOF'
FROM ./your-model.gguf
TEMPLATE """<|im_start|>system
{{ .System }}<|im_end|>
<|im_start|>user
{{ .Prompt }}<|im_end|>
<|im_start|>assistant
"""
PARAMETER stop "<|im_end|>"
PARAMETER temperature 0.1
EOF

ollama create mymodel -f Modelfile
```

Then set `AI_MODEL=mymodel` in `.env`.

### Running locally (development)

```bash
ollama serve
```

Ollama listens on `http://localhost:11434` by default.

### Running Ollama for production

When traick is deployed remotely (e.g. Fly.io) but you want to run the AI model on your own machine, expose Ollama through nginx (for API key authentication) and cloudflared (for a public HTTPS URL without opening firewall ports).

```
Internet → cloudflared → nginx (port 11435, checks API key) → Ollama (port 11434, localhost only)
```

**1. Keep Ollama on localhost only**

```bash
export OLLAMA_HOST=127.0.0.1:11434
ollama serve
```

**2. Install nginx and configure API key authentication**

```bash
sudo apt install nginx
```

Create `/etc/nginx/sites-available/ollama`:

```nginx
server {
    listen 11435;

    location / {
        if ($http_authorization != "Bearer your-secret-api-key") {
            return 401 '{"error":"Unauthorized"}';
        }

        proxy_pass http://127.0.0.1:11434;
        proxy_http_version 1.1;
        proxy_set_header Host $host;

        # Required for streaming LLM responses
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

Enable and reload:

```bash
sudo ln -s /etc/nginx/sites-available/ollama /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

**3. Expose via cloudflared**

Set up a named tunnel pointing at nginx:

```bash
cloudflared tunnel create ollama
cloudflared tunnel route dns ollama ollama.<your-domain>
```

Add to `~/.cloudflared/config.yml`:

```yaml
tunnel: ollama
credentials-file: /home/<your-user>/.cloudflared/<TUNNEL-UUID>.json
ingress:
  - hostname: ollama.<your-domain>
    service: http://localhost:11435
  - service: http_status:404
```

```bash
cloudflared tunnel run ollama
```

**4. Set in your production `.env`**

```
OLLAMA_BASE_URL=https://ollama.<your-domain>
OLLAMA_API_KEY=your-secret-api-key
```

---

## Configuration

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | | Ollama server URL (default: `http://localhost:11434`) |
| `OLLAMA_API_KEY` | | API key if Ollama is exposed publicly (default: `ollama`) |
| `AI_MODEL` | | Model to use (default: `qwen2.5:7b`) |
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

Start the server:

```bash
uvicorn traick.main:app --reload
```

Expose it with cloudflared.

Quick test (temporary URL that changes on restart):

```bash
cloudflared tunnel --url http://localhost:8000
```

Own domain (recommended):

Prerequisites:
- Your domain is managed in Cloudflare DNS.
- `cloudflared` is installed on the machine running traick.

```bash
# Authenticate cloudflared with your Cloudflare account
cloudflared tunnel login

# Create a named tunnel (one-time)
cloudflared tunnel create traick
```

Save the tunnel UUID from the output (used below as `<TUNNEL-UUID>`).

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: traick
credentials-file: /home/<your-user>/.cloudflared/<TUNNEL-UUID>.json
ingress:
  - hostname: whatsapp-webhook.<your-domain>
    service: http://localhost:8000
  - service: http_status:404
```

Then route DNS and run the tunnel:

```bash
cloudflared tunnel route dns traick whatsapp-webhook.<your-domain>
cloudflared tunnel run traick
```

Optional (production): run cloudflared as a service:

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

In the Meta dashboard under *Webhooks*:

- **Callback URL**: `https://whatsapp-webhook.<your-domain>/webhook` (or your `trycloudflare.com` URL if using quick test)
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

The AI will extract projects, action items, and deadlines from the file and save them to the database, scoped to your `TO_PHONE_NUMBER`.

---

## Running locally

```bash
# 1. Start Ollama (in a separate terminal)
ollama serve

# 2. Start traick (development, auto-reload on file changes)
uvicorn traick.main:app --reload

# 3. Production
traick
# or: uvicorn traick.main:app --host 0.0.0.0 --port 8000
```

The server starts on port `8000`. Check it's up:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## Deploying to Fly.io

Requires a [Fly.io](https://fly.io) account and the `flyctl` CLI.

```bash
brew install flyctl
fly auth login
```

**1. Create the app and persistent volume**

```bash
fly apps create traick
fly volumes create traick_data --region cdg --size 1
```

**2. Set secrets**

```bash
fly secrets import < .env.production
```

Make sure `.env.production` includes `OLLAMA_BASE_URL` pointing at your publicly accessible Ollama instance (see [Running Ollama for production](#running-ollama-for-production)) and `OLLAMA_API_KEY` if authentication is enabled.

**3. Deploy**

```bash
fly deploy
```

**4. Register the webhook in Meta dashboard**

Go to [developers.facebook.com](https://developers.facebook.com) → your app → WhatsApp → Configuration:

- **Callback URL**: `https://traick.fly.dev/webhook`
- **Verify token**: the value you set in `WHATSAPP_VERIFY_TOKEN`
- **Subscriptions**: check `messages`

Click **Verify and save**. The running app will respond to Meta's verification request automatically.

**5. Create the reminder template (one-time)**

```bash
fly ssh console
traick-setup
```

This submits the WhatsApp message template to Meta for approval (usually approved within minutes).

**6. Add your custom domain (optional)**

```bash
fly certs add yourdomain.com
fly certs show yourdomain.com   # get the IPs to point DNS to
```

Then update the Meta webhook URL to `https://yourdomain.com/webhook`.

**Useful commands**

```bash
fly logs          # tail live logs
fly ssh console   # SSH into the running container
fly status        # check app health
```

---

## Project structure

```
traick/
├── main.py              # FastAPI app + APScheduler startup
├── config.py            # Settings from .env
├── ai/
│   ├── client.py        # Ollama/OpenAI client singleton
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
INFO  traick.ai.extractor     Extracted 3 project updates from 7 messages
INFO  traick.scheduler.jobs   Scheduled follow-up for 'Website redesign' in 3 days
INFO  traick.scheduler.jobs   Done — marked 7 messages as processed
INFO  traick.whatsapp.sender  Sent template message to 15559876543
```

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
