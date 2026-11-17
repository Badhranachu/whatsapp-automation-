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
│   ├── .env             local secrets (git-ignored)
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

### Configure `backend/.env`
Open `backend/.env` and replace the placeholder:

```env
WHATSAPP_ACCESS_TOKEN=PASTE_NEW_META_ACCESS_TOKEN_HERE   # <-- paste your NEW token here
WHATSAPP_PHONE_NUMBER_ID=PASTE_YOUR_PHONE_NUMBER_ID_HERE
WHATSAPP_GRAPH_API_VERSION=v26.0
```
Restart Django after editing. Never commit `.env`. The token never goes to the frontend.
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
| "WhatsApp credentials are not configured" | `.env` token still a placeholder, or Django not restarted. |
| Browser CORS error | `FRONTEND_ORIGIN` in `.env` must match the frontend URL exactly. |

## Security (before any public deployment)
This is a local development tool. The API has **no authentication** — anyone who can reach it can send messages from your number. Before deploying add: authentication, HTTPS, rate limiting, `DEBUG=False`, a strong `SECRET_KEY`, restricted `ALLOWED_HOSTS`/CORS, and a long-lived System User token stored in a secrets manager. Never commit or share access tokens.
