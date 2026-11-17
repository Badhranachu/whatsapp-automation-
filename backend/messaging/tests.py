from unittest.mock import MagicMock, patch

from django.test import override_settings
from rest_framework.test import APITestCase

URL = '/api/send-message/'
CREDS = dict(
    WHATSAPP_ACCESS_TOKEN='test-token',
    WHATSAPP_PHONE_NUMBER_ID='123',
    WHATSAPP_GRAPH_API_VERSION='v26.0',
)


def fake_response(status_code, body):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = body
    return r


@override_settings(**CREDS)
class SendMessageTests(APITestCase):
    def post(self, data):
        return self.client.post(URL, data, format='json')

    def test_missing_phone(self):
        r = self.post({'message': 'hi'})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()['success'])

    def test_invalid_phone(self):
        for bad in ['abc', '123', '+0123456789', '9' * 20]:
            self.assertEqual(self.post({'phone_number': bad, 'message': 'hi'}).status_code, 400, bad)

    def test_missing_message(self):
        self.assertEqual(self.post({'phone_number': '919876543210'}).status_code, 400)
        self.assertEqual(self.post({'phone_number': '919876543210', 'message': '  '}).status_code, 400)

    @override_settings(WHATSAPP_ACCESS_TOKEN='')
    def test_missing_credentials(self):
        r = self.post({'phone_number': '919876543210', 'message': 'hi'})
        self.assertEqual(r.status_code, 500)
        self.assertFalse(r.json()['success'])

    @patch('messaging.services.requests.post')
    def test_success(self, mock_post):
        mock_post.return_value = fake_response(200, {'messages': [{'id': 'wamid.abc'}]})
        r = self.post({'phone_number': '+91 98765-43210', 'message': 'hello'})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['message_id'], 'wamid.abc')
        self.assertNotIn('test-token', r.content.decode())
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], 'https://graph.facebook.com/v26.0/123/messages')
        self.assertEqual(kwargs['json']['to'], '919876543210')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test-token')

    @patch('messaging.services.requests.post')
    def test_meta_failure(self, mock_post):
        mock_post.return_value = fake_response(
            400, {'error': {'message': 'Recipient phone number not in allowed list', 'code': 131030}}
        )
        r = self.post({'phone_number': '919876543210', 'message': 'hello'})
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertFalse(body['success'])
        self.assertIn('allowed list', body['error'])
