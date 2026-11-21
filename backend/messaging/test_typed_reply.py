import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import FlowRun, FlowStep, MessageLog, MessageTemplate, Option, Question, add_step

CREDS = dict(
    WHATSAPP_ACCESS_TOKEN='t', WHATSAPP_PHONE_NUMBER_ID='1', WHATSAPP_GRAPH_API_VERSION='v26.0',
    WHATSAPP_VERIFY_TOKEN='v', WHATSAPP_APP_SECRET='', WEBHOOK_ALLOW_UNSIGNED=True,
)
PHONE = '919876543210'


def text_payload(body, wa_id='wamid.in1', sender=PHONE):
    return {'entry': [{'changes': [{'value': {'messages': [
        {'from': sender, 'id': wa_id, 'type': 'text', 'text': {'body': body}}]}}]}]}


class JsonApi(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_superuser('boss', 'b@example.com', 'pw-12345-x'))
        self.tpl = MessageTemplate.objects.create(name='S')


class ReplySettingsTests(JsonApi):
    def test_create_patch_and_validation(self):
        url = f'/api/templates/{self.tpl.id}/questions/'
        root = self.client.post(url, {'text': 'Q', 'options': ['a']}, format='json').json()
        opt = Option.objects.get(question_id=root['id'])
        # a question with options cannot ask for a typed reply
        bad = self.client.post(url, {'text': 'Q2', 'options': ['x'], 'wants_reply': True}, format='json')
        self.assertEqual(bad.status_code, 400)
        end = self.client.post(url, {'text': 'Tell us more', 'option_id': opt.id, 'wants_reply': True,
                                     'reply_thanks': ' Thanks! '}, format='json')
        self.assertEqual(end.status_code, 201, end.content)
        q = Question.objects.get(pk=end.json()['id'])
        self.assertEqual((q.wants_reply, q.reply_thanks), (True, 'Thanks!'))
        r = self.client.patch(f'/api/questions/{q.id}/', {'wants_reply': False}, format='json')
        self.assertEqual(r.status_code, 200)
        q.refresh_from_db()
        self.assertEqual((q.wants_reply, q.reply_thanks, q.text), (False, '', 'Tell us more'))
        self.assertEqual(self.client.patch(f'/api/questions/{root["id"]}/', {'wants_reply': True}, format='json').status_code, 400)

    def test_json_import_and_sync_carry_the_settings(self):
        flow = {'text': 'Q', 'options': [{'title': 'Idea', 'next': {
            'text': 'Type it', 'wants_reply': True, 'reply_thanks': 'Got it!'}}]}
        r = self.client.post(f'/api/templates/{self.tpl.id}/import-flow/', flow, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        end = Question.objects.get(text='Type it')
        self.assertEqual((end.wants_reply, end.reply_thanks), (True, 'Got it!'))
        tree = self.client.get(f'/api/templates/{self.tpl.id}/flow/').json()['root']
        self.assertTrue(tree['options'][0]['next']['wants_reply'])
        # sync: switch it off in place
        tree_json = {'id': tree['id'], 'text': 'Q', 'options': [{
            'id': tree['options'][0]['id'], 'title': 'Idea',
            'next': {'id': end.id, 'text': 'Type it', 'wants_reply': False}}]}
        r = self.client.post(f'/api/templates/{self.tpl.id}/sync-flow/', tree_json, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        end.refresh_from_db()
        self.assertFalse(end.wants_reply)
        bad = {'text': 'Q', 'wants_reply': True, 'options': [{'title': 'a', 'next': {'text': 'b'}}]}
        t2 = MessageTemplate.objects.create(name='T2')
        self.assertEqual(self.client.post(f'/api/templates/{t2.id}/import-flow/', bad, format='json').status_code, 400)


@override_settings(**CREDS)
class WebhookReplyTests(TestCase):
    def setUp(self):
        self.tpl = MessageTemplate.objects.create(name='S')
        q = Question.objects.create(template=self.tpl, text='Start')
        opt = Option.objects.create(question=q, title='Idea')
        self.end = Question.objects.create(template=self.tpl, text='Type your idea', parent_option=opt,
                                           wants_reply=True, reply_thanks='Thanks, saved!')
        self.run = FlowRun.objects.create(template=self.tpl, template_name='S', phone_number=PHONE,
                                          status=FlowRun.COMPLETED, current_question=self.end,
                                          current_text=self.end.text)

    def post(self, body, wa_id='wamid.in1'):
        return self.client.post('/webhook', json.dumps(text_payload(body, wa_id)), content_type='application/json')

    @patch('messaging.webhook.send_text_message', return_value='wamid.out1')
    def test_saves_one_reply_and_sends_the_thanks(self, send):
        self.assertEqual(self.post(' Make it faster ').status_code, 200)
        step = self.run.steps.get(kind=FlowStep.REPLY_RECEIVED)
        self.assertEqual((step.text, step.question_id), ('Make it faster', self.end.id))
        send.assert_called_once_with(PHONE, 'Thanks, saved!')
        self.assertTrue(MessageLog.objects.filter(direction='out', flow_run=self.run, content='Thanks, saved!').exists())
        self.assertEqual(MessageLog.objects.get(direction='in').flow_run_id, self.run.id)
        # a second message, and a re-delivery of the first, are not saved again
        self.post('another one', 'wamid.in2')
        self.post(' Make it faster ', 'wamid.in1')
        self.assertEqual(self.run.steps.filter(kind=FlowStep.REPLY_RECEIVED).count(), 1)
        self.assertEqual(send.call_count, 1)

    @patch('messaging.webhook.send_text_message')
    def test_ignored_when_not_asked_for(self, send):
        self.end.wants_reply = False
        self.end.save()
        self.post('hello')
        self.assertFalse(self.run.steps.filter(kind=FlowStep.REPLY_RECEIVED).exists())
        send.assert_not_called()

    @patch('messaging.webhook.send_text_message')
    def test_ignored_outside_window_or_for_unfinished_or_unknown_numbers(self, send):
        FlowRun.objects.filter(pk=self.run.pk).update(updated_at=timezone.now() - timedelta(hours=25))
        self.post('too late')
        FlowRun.objects.filter(pk=self.run.pk).update(updated_at=timezone.now(), status=FlowRun.ACTIVE)
        self.post('still in the survey')
        self.client.post('/webhook', json.dumps(text_payload('who am i', 'wamid.in9', sender='911111111111')),
                         content_type='application/json')
        self.assertFalse(FlowStep.objects.filter(kind=FlowStep.REPLY_RECEIVED).exists())

    @patch('messaging.webhook.send_text_message', side_effect=__import__('messaging.services', fromlist=['x']).WhatsAppError('closed'))
    def test_thanks_failure_does_not_lose_the_reply(self, send):
        self.assertEqual(self.post('kept').status_code, 200)
        self.assertEqual(self.run.steps.filter(kind=FlowStep.REPLY_RECEIVED).count(), 1)

    @patch('messaging.webhook.send_text_message', return_value='wamid.out1')
    def test_shows_in_insights_run_detail_and_csv(self, send):
        self.post('Add dark mode')
        user = User.objects.create_superuser('t', 't@example.com', 'pw')
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(user=user)
        stats = c.get(f'/api/templates/{self.tpl.id}/stats/').json()
        self.assertEqual(stats['reply_total'], 1)
        self.assertEqual(stats['replies'][0]['text'], 'Add dark mode')
        end = next(f for f in stats['funnel'] if f['id'] == self.end.id)
        self.assertEqual((end['wants_reply'], end['replied']), (True, 1))
        detail = c.get(f'/api/flow-runs/{self.run.id}/').json()
        self.assertIn('reply_received', [s['kind'] for s in detail['steps']])
        csv_text = c.get(f'/api/templates/{self.tpl.id}/export/').content.decode()
        self.assertIn('typed_reply', csv_text)
        self.assertIn('Add dark mode', csv_text)
