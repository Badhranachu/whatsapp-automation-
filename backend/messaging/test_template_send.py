import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from .testutils import ReplyImageMixin
from .models import MessageLog, MessageTemplate, Option, Question

CREDS = dict(
    WHATSAPP_ACCESS_TOKEN='test-token',
    WHATSAPP_PHONE_NUMBER_ID='123',
    WHATSAPP_GRAPH_API_VERSION='v26.0',
    WHATSAPP_VERIFY_TOKEN='verify-me',
    WHATSAPP_APP_SECRET='',
)


def fake_response(status_code, body):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = body
    return r


OK = fake_response(200, {'messages': [{'id': 'wamid.x'}]})


def build_flow():
    tpl = MessageTemplate.objects.create(name='Survey', description='d')
    root = Question.objects.create(template=tpl, text='Are you a member?')
    yes = Option.objects.create(question=root, title='yes')
    no = Option.objects.create(question=root, title='no')
    follow = Question.objects.create(template=tpl, text='Which team?', parent_option=yes)
    Option.objects.create(question=follow, title='A')
    return tpl, root, yes, no, follow


def tap(sender, button_id, title):
    return {'entry': [{'changes': [{'value': {'messages': [{
        'from': sender, 'id': 'wamid.in', 'type': 'interactive',
        'interactive': {'type': 'button_reply', 'button_reply': {'id': button_id, 'title': title}},
    }]}}]}]}


@override_settings(**CREDS)
class TemplateSendTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_user('t', 't@example.com', 'pw'))
        self.tpl, self.root, self.yes, self.no, self.follow = build_flow()

    @patch('messaging.services.requests.post')
    def test_sends_first_question_with_option_buttons(self, mock_post):
        mock_post.return_value = OK
        r = self.client.post(f'/api/templates/{self.tpl.id}/send/', {'phone_number': '+91 98765 43210'}, format='json')
        self.assertEqual(r.status_code, 200)
        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(payload['to'], '919876543210')
        self.assertEqual(payload['type'], 'interactive')
        self.assertEqual(payload['interactive']['body']['text'], 'Are you a member?')
        buttons = payload['interactive']['action']['buttons']
        self.assertEqual([b['reply']['title'] for b in buttons], ['yes', 'no'])
        self.assertEqual(buttons[0]['reply']['id'], f'flow_opt_{self.yes.id}')
        log = MessageLog.objects.get()
        self.assertEqual((log.direction, log.message_type, log.content), ('out', 'flow', 'Are you a member?'))

    @patch('messaging.services.requests.post')
    def test_question_without_options_is_sent_as_text(self, mock_post):
        mock_post.return_value = OK
        tpl = MessageTemplate.objects.create(name='Plain', description='d')
        Question.objects.create(template=tpl, text='Just text')
        self.client.post(f'/api/templates/{tpl.id}/send/', {'phone_number': '919876543210'}, format='json')
        payload = mock_post.call_args.kwargs['json']
        self.assertEqual((payload['type'], payload['text']['body']), ('text', 'Just text'))

    @patch('messaging.services.requests.post')
    def test_template_without_questions_is_rejected(self, mock_post):
        empty = MessageTemplate.objects.create(name='Empty', description='d')
        r = self.client.post(f'/api/templates/{empty.id}/send/', {'phone_number': '919876543210'}, format='json')
        self.assertEqual(r.status_code, 400)
        mock_post.assert_not_called()

    @patch('messaging.services.requests.post')
    def test_invalid_phone_rejected(self, mock_post):
        r = self.client.post(f'/api/templates/{self.tpl.id}/send/', {'phone_number': 'abc'}, format='json')
        self.assertEqual(r.status_code, 400)
        mock_post.assert_not_called()

    @patch('messaging.services.requests.post')
    def test_sends_to_several_numbers(self, mock_post):
        mock_post.return_value = OK
        r = self.client.post(
            f'/api/templates/{self.tpl.id}/send/',
            {'phone_numbers': ['+91 98765 43210', '919846730362', '919876543210']},  # first and last are the same
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['success'])
        self.assertEqual([x['phone_number'] for x in body['results']], ['919876543210', '919846730362'])
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(MessageLog.objects.filter(direction='out').count(), 2)

    @patch('messaging.services.requests.post')
    def test_one_failure_does_not_stop_the_others(self, mock_post):
        mock_post.side_effect = [
            fake_response(400, {'error': {'message': 'Re-engagement message', 'code': 131047}}),
            OK,
        ]
        r = self.client.post(
            f'/api/templates/{self.tpl.id}/send/',
            {'phone_numbers': ['919876543210', '919846730362']},
            format='json',
        )
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(body['success'])
        self.assertEqual((body['sent'], body['failed']), (1, 1))
        self.assertFalse(body['results'][0]['success'])
        self.assertIn('Re-engagement', body['results'][0]['error'])
        self.assertTrue(body['results'][1]['success'])

    @patch('messaging.services.requests.post')
    def test_nothing_is_sent_if_any_number_is_invalid(self, mock_post):
        r = self.client.post(
            f'/api/templates/{self.tpl.id}/send/',
            {'phone_numbers': ['919876543210', 'abc']},
            format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['invalid'], ['abc'])
        mock_post.assert_not_called()

    @patch('messaging.services.requests.post')
    def test_recipient_list_limits(self, mock_post):
        url = f'/api/templates/{self.tpl.id}/send/'
        self.assertEqual(self.client.post(url, {'phone_numbers': []}, format='json').status_code, 400)
        many = [f'9198765{n:05d}' for n in range(51)]
        self.assertEqual(self.client.post(url, {'phone_numbers': many}, format='json').status_code, 400)
        mock_post.assert_not_called()

    def test_requires_login(self):
        self.client.force_authenticate(user=None)
        r = self.client.post(f'/api/templates/{self.tpl.id}/send/', {'phone_number': '919876543210'}, format='json')
        self.assertEqual(r.status_code, 401)


@override_settings(**CREDS)
class FlowWebhookTests(ReplyImageMixin, TestCase):
    def setUp(self):
        self.tpl, self.root, self.yes, self.no, self.follow = build_flow()

    def post(self, payload):
        return self.client.post('/webhook', json.dumps(payload), content_type='application/json')

    @patch('messaging.services.requests.post')
    def test_tap_sends_the_sub_question(self, mock_post):
        mock_post.return_value = OK
        r = self.post(tap('919876543210', f'flow_opt_{self.yes.id}', 'yes'))
        self.assertEqual(r.status_code, 200)
        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(payload['interactive']['body']['text'], 'Which team?')
        self.assertEqual([b['reply']['title'] for b in payload['interactive']['action']['buttons']], ['A'])
        self.assertEqual(MessageLog.objects.filter(direction='in').get().content, 'yes')

    @patch('messaging.services.requests.post')
    def test_tap_on_option_without_sub_question_ends_the_flow(self, mock_post):
        r = self.post(tap('919876543210', f'flow_opt_{self.no.id}', 'no'))
        self.assertEqual(r.status_code, 200)
        mock_post.assert_not_called()
        self.assertEqual(MessageLog.objects.filter(direction='in').count(), 1)

    @patch('messaging.services.requests.post')
    def test_unknown_or_garbled_flow_button_is_ignored(self, mock_post):
        for bad in ['flow_opt_99999', 'flow_opt_abc']:
            self.assertEqual(self.post(tap('919876543210', bad, 'x')).status_code, 200)
        mock_post.assert_not_called()

    @patch('messaging.services.requests.post')
    def test_demo_buttons_still_reply_with_image(self, mock_post):
        mock_post.side_effect = [fake_response(200, {'id': 'media1'}), OK]
        self.post(tap('919876543210', 'opt_1', 'yes I am'))
        self.assertEqual(mock_post.call_args.kwargs['json']['type'], 'image')
