# WhatsApp Messenger

A minimal web app that sends WhatsApp text messages through the official **Meta WhatsApp Cloud API**.
Django REST Framework backend (holds the secret token) + React/Vite frontend.

## Stack
- Backend: Python, Django 5.2, Django REST Framework, django-cors-headers, requests, python-dotenv, SQLite (default, unused for data)
- Frontend: React, Vite, Axios, plain CSS

## Structure
```text
whatsapp-messenger/
├── backend/
│   ├── config/          Django project (settings, urls)
│   ├── messaging/       App: serializers, services (Meta client), views, tests
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env.dev         local development secrets (git-ignored)
│   ├── .env.prod        production server secrets (git-ignored, never committed)
│   └── .env.example
├── frontend/
│   ├── src/components/  MessageForm, StatusPanel
│   ├── src/services/    api.js (Axios)
│   ├── src/App.jsx, App.css, main.jsx
│   ├── package.json
│   └── .env.example
├── .gitignore
└── README.md
```

## Prerequisites
Python 3.11+ and Node.js 20+ with npm.

## Setup

### Backend
```powershell
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
```

### Configure `backend/.env.dev`
Development reads `backend/.env.dev` (copy `.env.example` if it is missing). Open it and replace the placeholder:

```env
WHATSAPP_ACCESS_TOKEN=PASTE_NEW_META_ACCESS_TOKEN_HERE   # <-- paste your NEW token here
WHATSAPP_PHONE_NUMBER_ID=PASTE_YOUR_PHONE_NUMBER_ID_HERE
WHATSAPP_GRAPH_API_VERSION=v26.0
```
Restart Django after editing. Never commit `.env.dev` or `.env.prod`. The token never goes to the frontend.
Revoke any token that was ever exposed publicly.

### Frontend
```powershell
cd frontend
npm install
copy .env.example .env
```
(The frontend falls back to `http://127.0.0.1:8000/api` if `.env` is absent.)

## Run
```powershell
# Terminal 1
cd backend
venv\Scripts\activate
python manage.py runserver        # http://127.0.0.1:8000

# Terminal 2
cd frontend
npm run dev                       # http://localhost:5173
```

## Tests
```powershell
cd backend
python manage.py check
python manage.py test             # Meta API is mocked; no real messages sent
cd ../frontend
npm run build
```

## API

### `POST /api/send-message/`
```json
{ "phone_number": "919876543210", "message": "Hello!" }
```
`phone_number` accepts `+`, spaces, dashes; it is normalized to digits (E.164 without `+`, 8–15 digits). `message` max 4096 chars.

Success (200):
```json
{ "success": true, "message": "Message accepted by Meta.", "message_id": "wamid.xxx" }
```
Failure (400 invalid input / Meta rejection, 401 bad token, 500 server not configured, 502 Meta unreachable):
```json
{ "success": false, "message": "Unable to send WhatsApp message.", "error": "..." }
```
**Success means Meta accepted the request, not that the recipient received or read it.**

```powershell
curl -X POST http://127.0.0.1:8000/api/send-message/ -H "Content-Type: application/json" `
  -d '{\"phone_number\":\"919876543210\",\"message\":\"Hello!\"}'
```

## WhatsApp messaging policy
- Recipients must have opted in to receive messages from your business.
- Free-form text is generally only allowed within the **24-hour customer service window** after the user last messaged you.
- Outside that window, business-initiated messages generally require an **approved message template**. Template support is not implemented in this version.
- Not every message can be sent to any number at any time.
- With a test number, recipients must be added to the allowed list in the Meta developer dashboard.

## Troubleshooting
| Error | Likely cause |
|---|---|
| 190 / 401 "Invalid OAuth access token" | Token expired/wrong. Temporary tokens last ~24h; generate a new one (or a System User token). |
| 131030 "Recipient not in allowed list" | Add the number as a test recipient in the Meta dashboard. |
| 131047 "Re-engagement message" | Outside the 24-hour window; a template is required. |
| 131026 "Message undeliverable" | Number is not on WhatsApp or hasn't accepted terms. |
| 100 "Unsupported post request" | Wrong Phone Number ID or API version. |
| 10 / 200 permission errors | Token lacks `whatsapp_business_messaging` permission. |
| "WhatsApp credentials are not configured" | `.env.dev` token still a placeholder, or Django not restarted. |
| Browser CORS error | `FRONTEND_ORIGIN` in `.env.dev` must match the frontend URL exactly. |

## Security (before any public deployment)
This is a local development tool. The API has **no authentication** — anyone who can reach it can send messages from your number. Before deploying add: authentication, HTTPS, rate limiting, `DEBUG=False`, a strong `SECRET_KEY`, restricted `ALLOWED_HOSTS`/CORS, and a long-lived System User token stored in a secrets manager. Never commit or share access tokens.

## Production (Docker, Ubuntu server)
Production uses `docker-compose.yml` and **only** `backend/.env.prod`; `.env.dev` is never loaded by the containers.
Fill in every `REPLACE_WITH_...` value in `.env.prod` (the backend refuses to start until you do), then:
```bash
chmod 600 backend/.env.prod
docker compose config --quiet      # validate; do not run plain `docker compose config` (it prints secrets)
docker compose up -d --build
```

## Auto deploy (GitHub Actions -> production server)
Every push to `main` is stored on GitHub. It is **deployed to the server only when the latest commit
message contains `[prod]`**:
```bash
git commit -m "Fix history filter [prod]"
git push origin main
```
The workflow (`.github/workflows/deploy.yml`) connects to the server over SSH, runs
`git pull --ff-only origin main` in `/var/www/whatsapp-automation-bot` and then `bash deploy.sh`, which
validates everything first and stops without changing anything if a check fails. A failed deploy shows
as a red run in the repository's **Actions** tab. Two deploys never run at the same time.

### One-time setup
**1. The server must be able to pull the code** (read-only key for the private repo). On the server:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/wa_github_read -N "" -C "wa-server-read"
cat ~/.ssh/wa_github_read.pub        # add it at GitHub: repo > Settings > Deploy keys (leave "write" OFF)
cd /var/www/whatsapp-automation-bot
git config core.sshCommand "ssh -i ~/.ssh/wa_github_read -o IdentitiesOnly=yes"
git remote set-url origin git@github.com:Badhranachu/whatsapp-automation-.git
git fetch origin main                # must work without a password prompt
```
**2. Create a separate SSH key just for the workflow** (on your PC, not on the server):
```bash
ssh-keygen -t ed25519 -f wa_actions_deploy -N "" -C "wa-actions-deploy"
```
Add the **public** key to the deploy user's `~/.ssh/authorized_keys` on the server as ONE line that can
only run the deployment (nothing else, no tunnels):
```
command="cd /var/www/whatsapp-automation-bot && git pull --ff-only origin main && bash deploy.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA...your-public-key... wa-actions-deploy
```
**3. Add these repository secrets** (GitHub: repo > Settings > Secrets and variables > Actions):

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | server address |
| `DEPLOY_USER` | the SSH user that owns `/var/www/whatsapp-automation-bot` (must be in the `docker` group) |
| `DEPLOY_PORT` | SSH port (leave unset for 22) |
| `DEPLOY_SSH_KEY` | contents of the **private** file `wa_actions_deploy` |
| `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan -p 22 <server address>` (pins the server's identity) |

**4. On the server:** `backend/.env.prod` must exist and be filled in (it is never in Git), and
`bash deploy.sh --check-only` must pass. Delete the private key file from your PC after saving it as a secret.
