import logging
import mimetypes
import os

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15

# Image sent back when either button is tapped.
REPLY_IMAGE_PATH = settings.BASE_DIR / 'media' / 'image.png'


class ConfigurationError(Exception):
    pass


class WhatsAppError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def _post_message(payload):
    """POST a payload to the Meta messages endpoint; return the message id."""
    token = settings.WHATSAPP_ACCESS_TOKEN
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    version = settings.WHATSAPP_GRAPH_API_VERSION
    if not token or token.startswith('PASTE_') or not phone_id or not version:
        raise ConfigurationError('WhatsApp credentials are not configured on the server.')

    url = f'https://graph.facebook.com/{version}/{phone_id}/messages'
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


def send_template_message(to):
    template_name = settings.WHATSAPP_TEMPLATE_NAME
    template_lang = settings.WHATSAPP_TEMPLATE_LANG
    if not template_name or not template_lang:
        raise ConfigurationError('WhatsApp credentials are not configured on the server.')
    return _post_message({
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'template',
        'template': {
            'name': template_name,
            'language': {'code': template_lang},
        },
    })


def send_buttons_message(to, body, options):
    """Send `body` with up to 3 reply buttons. options: [{'id': str, 'title': str}].

    Free-form interactive messages only work inside the 24-hour customer
    service window (the recipient must have messaged the business recently).
    """
    return _post_message({
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'interactive',
        'interactive': {
            'type': 'button',
            'body': {'text': body},
            'action': {
                'buttons': [{'type': 'reply', 'reply': option} for option in options],
            },
        },
    })


def _upload(fh, filename, mime):
    """Upload an open file to Meta's media endpoint; return the media id."""
    token = settings.WHATSAPP_ACCESS_TOKEN
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    version = settings.WHATSAPP_GRAPH_API_VERSION
    if not token or token.startswith('PASTE_') or not phone_id or not version:
        raise ConfigurationError('WhatsApp credentials are not configured on the server.')
    url = f'https://graph.facebook.com/{version}/{phone_id}/media'
    try:
        resp = requests.post(
            url,
            headers={'Authorization': f'Bearer {token}'},
            data={'messaging_product': 'whatsapp', 'type': mime},
            files={'file': (filename, fh, mime)},
            timeout=TIMEOUT_SECONDS * 2,
        )
    except requests.RequestException as exc:
        logger.error('Network error uploading media: %s', type(exc).__name__)
        raise WhatsAppError('Could not reach the Meta API.', 502)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or not data.get('id'):
        err = data.get('error', {}) if isinstance(data, dict) else {}
        logger.warning('Meta media upload failed status=%s code=%s', resp.status_code, err.get('code'))
        raise WhatsAppError(err.get('message') or 'Media upload failed.', 502)
    return data['id']


def _image_payload(to, media_id, caption=''):
    image = {'id': media_id}
    if caption:
        image['caption'] = caption
    return {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'image',
        'image': image,
    }


def send_image_message(to, path=None):
    """Send a local image file (used for the button-reply image)."""
    path = path or REPLY_IMAGE_PATH  # looked up at call time so tests can point it at a temporary file
    mime = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
    try:
        with open(path, 'rb') as fh:
            media_id = _upload(fh, os.path.basename(path), mime)
    except OSError:
        raise ConfigurationError('Reply image file not found on the server.')
    return _post_message(_image_payload(to, media_id))


def send_uploaded_image(to, fh, filename, mime, caption=''):
    """Send an image uploaded through the website, with an optional caption.

    Free-form media only works inside the 24-hour customer service window.
    """
    media_id = _upload(fh, filename, mime)
    return _post_message(_image_payload(to, media_id, caption))


def send_text_message(to, body):
    return _post_message({
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'text',
        'text': {'preview_url': False, 'body': body},
    })
