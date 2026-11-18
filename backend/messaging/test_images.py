from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

CREDS = dict(
    WHATSAPP_ACCESS_TOKEN='test-token',
    WHATSAPP_PHONE_NUMBER_ID='123',
    WHATSAPP_GRAPH_API_VERSION='v26.0',
    WHATSAPP_TEMPLATE_NAME='test_notification',
    WHATSAPP_TEMPLATE_LANG='en',
)
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 64


def fake_response(status_code, body):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = body
    return r


@override_settings(**CREDS)
class ImageUploadTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_user('t', 't@example.com', 'pw'))

    def upload(self, content=PNG, name='pic.png', **extra):
        data = {
            'phone_number': '+91 98765 43210',
            'image': SimpleUploadedFile(name, content, 'image/png'),
        }
        data.update(extra)
        return self.client.post('/api/send-message/', data, format='multipart')

    @patch('messaging.services.requests.post')
    def test_image_with_caption_is_uploaded_then_sent(self, mock_post):
        from messaging.models import MessageLog

        mock_post.side_effect = [
            fake_response(200, {'id': 'media9'}),
            fake_response(200, {'messages': [{'id': 'wamid.img'}]}),
        ]
        r = self.upload(message='look at this')
        self.assertEqual(r.status_code, 200)
        upload, send = mock_post.call_args_list
        self.assertTrue(upload.args[0].endswith('/123/media'))
        self.assertEqual(send.kwargs['json']['type'], 'image')
        self.assertEqual(send.kwargs['json']['to'], '919876543210')
        self.assertEqual(send.kwargs['json']['image'], {'id': 'media9', 'caption': 'look at this'})
        row = MessageLog.objects.get()
        self.assertEqual((row.message_type, row.content), ('image', 'look at this'))

    @patch('messaging.services.requests.post')
    def test_rejects_non_image_content(self, mock_post):
        r = self.upload(content=b'not an image at all', name='evil.png')
        self.assertEqual(r.status_code, 400)
        mock_post.assert_not_called()

    @patch('messaging.services.requests.post')
    def test_rejects_oversized_image(self, mock_post):
        r = self.upload(content=PNG + b'0' * (5 * 1024 * 1024))
        self.assertEqual(r.status_code, 400)
        mock_post.assert_not_called()

    @patch('messaging.services.requests.post')
    def test_no_image_still_sends_template(self, mock_post):
        mock_post.return_value = fake_response(200, {'messages': [{'id': 'wamid.t'}]})
        r = self.client.post('/api/send-message/', {'phone_number': '919876543210'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(mock_post.call_args.kwargs['json']['type'], 'template')
