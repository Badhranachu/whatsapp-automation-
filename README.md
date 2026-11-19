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

## CI/CD: GitHub Actions -> SSH -> server-side deploy script
A push to `main` is deployed to production **only when the HEAD commit message contains `[prod]`**:
```bash
git add .
git commit -m "Improve webhook processing [prod]"
git push origin main
```
A push without `[prod]` is only stored on GitHub; nothing runs on the server. A destructive database migration
additionally needs `[migrate-ok]` (see below).

### What happens (`.github/workflows/deploy.yml`)
1. **detect-gate**: branch is `main` and the message contains `[prod]`; the exact 40-character commit SHA is passed on.
2. **backend-validate** (Python 3.12), **frontend-validate** (Node 22), **docker-validate**: run in parallel on that exact SHA.
   They run `pip install -r requirements.txt -c constraints.txt` + `pip check`, the Django checks, `check --deploy`
   (with temporary dummy values), `makemigrations --check --dry-run`, all backend tests, `npm ci`, lint and the
   production build, the deployment-script tests, `docker compose config`, and a BuildKit build of both images
   (GitHub cache, nothing is pushed). Any failure stops everything; production is not touched.
3. **deploy**: one SSH call that sends **only the validated SHA**. Runs one at a time (`concurrency`), plus a server-side lock.
4. **report**: a summary on the run page.

### What the server does (`deploy.sh`, with `scripts/lib/*`)
1. Takes an exclusive lock, checks that the SHA is 40 hex characters, the working tree is clean, the commit is on
   `origin/main` and its message has `[prod]`, then checks out **exactly that SHA** (never `git pull`).
2. Pre-flight: `.env.prod` has no placeholders, `DEBUG=False`, ports, Compose config.
3. **Change detection** against the last successfully deployed SHA (stored in `.git/deploy-state/`):

| Changed files | Action |
|---|---|
| backend source / `requirements.txt` / `constraints.txt` / backend Dockerfile | rebuild + deploy **backend** only |
| `backend/messaging/migrations/*` | backend, plus backup + migrate |
| frontend source / `package.json` / lockfile / frontend Dockerfile / `nginx.conf` | rebuild + deploy **frontend** only |
| both | backend first (verified), then frontend |
| `docker-compose.yml` or any unknown path | both (conservative); Docker's cache and Compose only recreate what really changed |
| docs, tests, CI, `deploy.sh`, `scripts/*` | no rebuild, no restart; the SHA is recorded |

4. The running images are kept as `:previous`; only the changed services are built (`latest` + the commit SHA tag).
5. If migrations are pending: committed-migration check, `migrate --plan`, a scan for risky operations, a verified
   SQLite backup, then `migrate` **once** (migrations no longer run when the container starts).
6. Backend deploy -> health + `/api/health/` + API checks; frontend deploy -> health + page checks; final end-to-end
   check through ports 8000 and 8003. Only then the SHA is recorded as deployed.
7. Cleanup: only this project's old image tags (keeps `latest`, `previous` and the deployed SHA), never a global prune.

### Migration approval and backups
- Operations `RemoveField`, `DeleteModel`, `RenameModel`, `RenameField`, `AlterField`, `AlterModelTable`, `RunPython`,
  `RunSQL`, `SeparateDatabaseAndState`, `RemoveIndex`, `RemoveConstraint` stop the deployment **before anything is
  changed** unless the commit message also contains `[migrate-ok]`: `git commit -m "Drop old column [prod] [migrate-ok]"`.
- A backup is taken only when migrations are pending. It uses SQLite's online backup, is verified, and is written to
  the volume (`/data/backups`) **and** to `/var/backups/whatsapp-automation-bot/` as `db-<UTC time>-<sha>.sqlite3`.
  The 14 newest are kept in each place; the newest verified backup is never deleted.
- Migrations are **never reversed automatically**, and the database is **never restored automatically**.

### Rollback
- A failure after a container was replaced restores that service's `:previous` image, recreates only that service and
  waits for it to be healthy. If the frontend (or the final check) fails after the backend was updated, **both** are restored.
- If migrations were already applied, the log says so and points to the backups. The old backend image may not run
  against a migrated schema; additive migrations normally do. Restore a backup manually if needed (steps in `scripts/lib/backup.sh`).
- Manual rollback of one service:
  ```bash
  docker tag whatsapp-automation-bot-backend:previous whatsapp-automation-bot-backend:latest
  docker compose up -d --no-deps --no-build backend
  ```
  (a specific commit: `BACKEND_IMAGE_TAG=<sha> docker compose up -d --no-deps --no-build backend`)
- Failure logs (secrets masked) are saved in `.git/deploy-state/failures/`; deployment history in `.git/deploy-state/history.log`.

### GitHub secrets: no new ones
`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` and the optional `DEPLOY_PORT` are all that is needed.
No new environment variable or `.env` field is required.

### One-time cutover on the server (in this order)
1. Merge this change **without** `[prod]` in the commit message, so nothing deploys yet.
2. On the server (once): `cd /var/www/whatsapp-automation-bot && git pull --ff-only origin main`, then `bash deploy.sh --check-only`.
   (`flock`, `curl`, `ss` and Docker Compose must be available.)
3. Replace the workflow key's line in `~/.ssh/authorized_keys` so it accepts only a commit SHA (ONE line):
   ```
   command="cd /var/www/whatsapp-automation-bot && bash deploy.sh --from-ssh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA...your-public-key... wa-actions-deploy
   ```
   sshd hands the requested command to the script in `SSH_ORIGINAL_COMMAND`; anything that is not exactly one 40-character
   hexadecimal SHA is rejected. (The old forced command `git pull ... && bash deploy.sh` still works for one transition
   deployment, but leaves the repository on a detached commit, so switch to the line above before the second deployment.)
4. Push a commit with `[prod]`. The first deployment rebuilds both services (no SHA recorded yet) and keeps the running
   images as `:previous`.

### Manual use on the server
`bash deploy.sh --check-only` (pre-flight only) | `bash deploy.sh <sha>` (deploy that commit; its message needs `[prod]`).

### Troubleshooting
| Message | Meaning |
|---|---|
| `SSH command rejected` | the forced command received something other than a 40-hex SHA |
| `working tree has uncommitted or untracked changes` | someone edited files on the server; clean them (never overwritten automatically) |
| `another deployment is already running` | the lock is held; wait for it to finish |
| `... without [migrate-ok]` | a risky migration; review it, then push again with `[prod] [migrate-ok]` |
| `DEPLOY RESULT: FAILED, previous version restored` | rolled back; read the log above it and `.git/deploy-state/failures/` |
| `... NOT fully successful: manual attention required` | the rollback could not restore a healthy service; see the log and the backups |

### Known limitations
- Replacing a container takes a few seconds, during which the API (backend) or the site (frontend) is unavailable; Meta retries failed webhook deliveries.
- The login and delete rate limits trust the `X-Forwarded-For` header (DRF `NUM_PROXIES` is not set). Setting it needs the real proxy count verified on the server first, so it is not changed here.
- If the SSH connection drops mid-deployment, the server script is interrupted and rolls back what it replaced.
- The dependency pins in `backend/constraints.txt` are the versions verified in the audit; change them deliberately.
