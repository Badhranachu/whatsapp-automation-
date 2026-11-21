import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from .testutils import ReplyImageMixin

CREDS = dict(
    WHATSAPP_ACCESS_TOKEN='test-token',
    WHATSAPP_PHONE_NUMBER_ID='123',
    WHATSAPP_GRAPH_API_VERSION='v26.0',
    WHATSAPP_VERIFY_TOKEN='verify-me',
    WHATSAPP_APP_SECRET='', WEBHOOK_ALLOW_UNSIGNED=True,
)


def fake_response(status_code, body):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = body
    return r


def tap_payload(sender='919876543210', title='hello hello'):
    return {
        'entry': [{'changes': [{'value': {'messages': [{
            'from': sender,
            'type': 'interactive',
            'interactive': {'type': 'button_reply', 'button_reply': {'id': 'opt_1', 'title': title}},
        }]}}]}]
    }


@override_settings(**CREDS)
class WebhookTests(ReplyImageMixin, TestCase):
    def test_verification_ok(self):
        r = self.client.get('/webhook', {
            'hub.mode': 'subscribe', 'hub.verify_token': 'verify-me', 'hub.challenge': '12345',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b'12345')

    def test_verification_wrong_token(self):
        r = self.client.get('/webhook', {
            'hub.mode': 'subscribe', 'hub.verify_token': 'nope', 'hub.challenge': '1',
        })
        self.assertEqual(r.status_code, 403)

    @patch('messaging.services.requests.post')
    def test_button_tap_replies_with_image(self, mock_post):
        mock_post.side_effect = [
            fake_response(200, {'id': 'media123'}),
            fake_response(200, {'messages': [{'id': 'wamid.y'}]}),
        ]
        r = self.client.post('/webhook', json.dumps(tap_payload(title='hay hello')),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(mock_post.call_count, 2)
        upload, send = mock_post.call_args_list
        self.assertTrue(upload.args[0].endswith('/123/media'))
        payload = send.kwargs['json']
        self.assertEqual(payload['type'], 'image')
        self.assertEqual(payload['to'], '919876543210')
        self.assertEqual(payload['image'], {'id': 'media123'})

    @patch('messaging.services.requests.post')
    def test_non_button_messages_ignored(self, mock_post):
        body = {'entry': [{'changes': [{'value': {'messages': [
            {'from': '919876543210', 'type': 'text', 'text': {'body': 'hi'}}]}}]}]}
        r = self.client.post('/webhook', json.dumps(body), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        mock_post.assert_not_called()

    @override_settings(WHATSAPP_APP_SECRET='shh')
    @patch('messaging.services.requests.post')
    def test_signature_enforced_when_secret_set(self, mock_post):
        mock_post.return_value = fake_response(200, {'messages': [{'id': 'wamid.y'}]})
        raw = json.dumps(tap_payload())
        bad = self.client.post('/webhook', raw, content_type='application/json',
                               HTTP_X_HUB_SIGNATURE_256='sha256=bad')
        self.assertEqual(bad.status_code, 403)
        mock_post.assert_not_called()
        sig = 'sha256=' + hmac.new(b'shh', raw.encode(), hashlib.sha256).hexdigest()
        ok = self.client.post('/webhook', raw, content_type='application/json',
                              HTTP_X_HUB_SIGNATURE_256=sig)
        self.assertEqual(ok.status_code, 200)
        mock_post.assert_called_once()


@override_settings(**CREDS)
class HistoryTests(ReplyImageMixin, APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_superuser('t', 't@example.com', 'pw'))

    @patch('messaging.services.requests.post')
    def test_sends_and_replies_are_saved_and_listed(self, mock_post):
        from messaging.models import MessageLog

        mock_post.return_value = fake_response(200, {'messages': [{'id': 'wamid.out1'}]})
        self.client.post('/api/send-message/', {'phone_number': '919876543210'}, format='json')

        mock_post.side_effect = [
            fake_response(200, {'id': 'media123'}),
            fake_response(200, {'messages': [{'id': 'wamid.out2'}]}),
        ]
        self.client.post('/webhook', json.dumps(tap_payload(title='yes I am')),
                         content_type='application/json')

        self.assertEqual(MessageLog.objects.count(), 3)
        rows = self.client.get('/api/messages/').json()
        self.assertEqual([(r['direction'], r['message_type']) for r in rows],
                         [('out', 'image'), ('in', 'button_reply'), ('out', 'template')])
        self.assertEqual(rows[1]['content'], 'yes I am')
        self.assertNotIn('test-token', json.dumps(rows))

    @patch('messaging.services.requests.post')
    def test_failed_send_is_not_logged(self, mock_post):
        from messaging.models import MessageLog

        mock_post.return_value = fake_response(400, {'error': {'message': 'nope', 'code': 1}})
        self.client.post('/api/send-message/', {'phone_number': '919876543210'}, format='json')
        self.assertEqual(MessageLog.objects.count(), 0)


def status_payload(wa_id, status, errors=None):
    st = {'id': wa_id, 'status': status, 'recipient_id': '919876543210'}
    if errors:
        st['errors'] = errors
    return {'entry': [{'changes': [{'value': {'statuses': [st]}}]}]}


@override_settings(**CREDS)
class StatusTests(APITestCase):
    def post_status(self, *args, **kw):
        return self.client.post('/webhook', json.dumps(status_payload(*args, **kw)),
                                content_type='application/json')

    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_superuser('t', 't@example.com', 'pw'))
        from messaging.models import MessageLog, log_message
        log_message(MessageLog.OUT, '919876543210', 'options', 'hi', 'wamid.s1')

    def status(self):
        return self.client.get('/api/messages/').json()[0]

    def test_progresses_and_ignores_out_of_order(self):
        self.assertEqual(self.status()['status'], 'accepted')
        self.post_status('wamid.s1', 'delivered')
        self.post_status('wamid.s1', 'sent')  # late, must not downgrade
        self.assertEqual(self.status()['status'], 'delivered')
        self.post_status('wamid.s1', 'read')
        self.assertEqual(self.status()['status'], 'read')

    def test_failure_saved_with_reason(self):
        self.post_status('wamid.s1', 'failed', [{'code': 131047, 'title': 'Re-engagement message'}])
        s = self.status()
        self.assertEqual(s['status'], 'failed')
        self.assertIn('131047', s['status_detail'])

    def test_unknown_message_id_ignored(self):
        self.assertEqual(self.post_status('wamid.nope', 'sent').status_code, 200)
