import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15


class ConfigurationError(Exception):
    pass


class WhatsAppError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def send_text_message(to, body):
    token = settings.WHATSAPP_ACCESS_TOKEN
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    version = settings.WHATSAPP_GRAPH_API_VERSION
    if not token or token.startswith('PASTE_') or not phone_id or not version:
        raise ConfigurationError('WhatsApp credentials are not configured on the server.')

    url = f'https://graph.facebook.com/{version}/{phone_id}/messages'
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'text',
        'text': {'preview_url': False, 'body': body},
    }
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={'Authorization': f'Bearer {token}'},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        # Log only the exception type: messages can embed the URL/headers.
        logger.error('Network error calling Meta API: %s', type(exc).__name__)
        raise WhatsAppError('Could not reach the Meta API.', 502)

    try:
        data = resp.json()
    except ValueError:
        data = {}

    if resp.status_code >= 400:
        err = data.get('error', {}) if isinstance(data, dict) else {}
        detail = err.get('message') or 'Meta API returned an error.'
        logger.warning('Meta API error status=%s code=%s', resp.status_code, err.get('code'))
        if resp.status_code == 401:
            status = 401
        elif resp.status_code < 500:
            status = 400
        else:
            status = 502
        raise WhatsAppError(detail, status)

    messages = data.get('messages') if isinstance(data, dict) else None
    if not messages or not messages[0].get('id'):
        raise WhatsAppError('Meta API returned an unexpected response.', 502)
    return messages[0]['id']
