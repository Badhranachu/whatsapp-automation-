import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from .models import FlowRun, FlowStep, MessageLog, MessageTemplate, Option, Question

CREDS = dict(
    WHATSAPP_ACCESS_TOKEN='test-token',
    WHATSAPP_PHONE_NUMBER_ID='123',
    WHATSAPP_GRAPH_API_VERSION='v26.0',
    WHATSAPP_VERIFY_TOKEN='verify-me',
    WHATSAPP_APP_SECRET='',
)


def resp(status_code, body):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = body
    return r


def ok(n=1):
    return resp(200, {'messages': [{'id': f'wamid.out{n}'}]})


def build():
    tpl = MessageTemplate.objects.create(name='Survey', description='d')
    root = Question.objects.create(template=tpl, text='Member?')
    yes = Option.objects.create(question=root, title='yes')
    no = Option.objects.create(question=root, title='no')
    q2 = Question.objects.create(template=tpl, text='Which team?', parent_option=yes)
    a = Option.objects.create(question=q2, title='A')
    note = Question.objects.create(template=tpl, text='Thanks, bye!', parent_option=a)  # end note (no options)
    return tpl, root, yes, no, q2, a, note


def tap(sender, option, wa_id):
    return {'entry': [{'changes': [{'value': {'messages': [{
        'from': sender, 'id': wa_id, 'type': 'interactive',
        'interactive': {'type': 'button_reply',
                        'button_reply': {'id': f'flow_opt_{option.id}', 'title': option.title}},
    }]}}]}]}


@override_settings(**CREDS)
class RunRecordingTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_user('t', 't@example.com', 'pw'))
        self.tpl, self.root, self.yes, self.no, self.q2, self.a, self.note = build()

    def send(self, numbers):
        return self.client.post(f'/api/templates/{self.tpl.id}/send/', {'phone_numbers': numbers}, format='json')

    def webhook(self, option, wa_id):
        return self.client.post('/webhook', json.dumps(tap('919876543210', option, wa_id)),
                                content_type='application/json')

    @patch('messaging.services.requests.post')
    def test_send_creates_a_run_with_its_first_step(self, mock_post):
        mock_post.return_value = ok()
        r = self.send(['919876543210', '919846730362'])
        self.assertEqual(r.json()['sent'], 2)
        self.assertEqual(FlowRun.objects.count(), 2)
        run = FlowRun.objects.get(phone_number='919876543210')
        self.assertEqual((run.status, run.template_name, run.current_question_id), ('active', 'Survey', self.root.id))
        step = run.steps.get()
        self.assertEqual((step.order, step.kind, step.text), (1, 'question_sent', 'Member?'))
        log = MessageLog.objects.filter(direction='out').first()
        self.assertEqual((log.template_id, log.flow_run_id is not None), (self.tpl.id, True))

    @patch('messaging.services.requests.post')
    def test_failed_send_is_saved_with_the_reason(self, mock_post):
        mock_post.return_value = resp(400, {'error': {'message': 'Re-engagement message', 'code': 131047}})
        r = self.send(['919876543210'])
        self.assertEqual(r.json()['failed'], 1)
        run = FlowRun.objects.get()
        self.assertEqual(run.status, 'failed')
        step = run.steps.get()
        self.assertEqual(step.kind, 'send_failed')
        self.assertIn('Re-engagement', step.detail)

    @patch('messaging.services.requests.post')
    def test_whole_journey_is_stored_in_order(self, mock_post):
        mock_post.side_effect = [ok(1), ok(2), ok(3)]
        self.send(['919876543210'])
        self.assertEqual(self.webhook(self.yes, 'wamid.tap1').status_code, 200)   # yes -> Which team?
        self.assertEqual(self.webhook(self.a, 'wamid.tap2').status_code, 200)     # A -> end note
        run = FlowRun.objects.get()
        steps = [(s.order, s.kind, s.text) for s in run.steps.all()]
        self.assertEqual(steps, [
            (1, 'question_sent', 'Member?'),
            (2, 'option_tapped', 'yes'),
            (3, 'question_sent', 'Which team?'),
            (4, 'option_tapped', 'A'),
            (5, 'question_sent', 'Thanks, bye!'),
        ])
        self.assertEqual(run.status, 'completed')  # the end note finished the flow
        self.assertEqual(run.current_text, 'Thanks, bye!')
        # incoming tap is tagged with the template for History
        tap_row = MessageLog.objects.filter(direction='in').first()
        self.assertEqual(tap_row.template_id, self.tpl.id)

    @patch('messaging.services.requests.post')
    def test_tapping_an_option_without_follow_up_completes_the_run(self, mock_post):
        mock_post.return_value = ok()
        self.send(['919876543210'])
        self.webhook(self.no, 'wamid.tap9')
        run = FlowRun.objects.get()
        self.assertEqual(run.status, 'completed')
        self.assertEqual([s.kind for s in run.steps.all()], ['question_sent', 'option_tapped'])

    @patch('messaging.services.requests.post')
    def test_redelivered_webhook_is_not_recorded_twice(self, mock_post):
        mock_post.side_effect = [ok(1), ok(2), ok(3)]
        self.send(['919876543210'])
        self.webhook(self.yes, 'wamid.same')
        self.webhook(self.yes, 'wamid.same')
        self.assertEqual(FlowStep.objects.filter(kind='option_tapped').count(), 1)
        self.assertEqual(mock_post.call_count, 2)  # first send + one follow-up only

    @patch('messaging.services.requests.post')
    def test_failure_sending_the_next_question_is_saved(self, mock_post):
        mock_post.side_effect = [ok(1), resp(400, {'error': {'message': 'window closed', 'code': 131047}})]
        self.send(['919876543210'])
        self.webhook(self.yes, 'wamid.t')
        run = FlowRun.objects.get()
        self.assertEqual(run.status, 'failed')
        self.assertEqual(run.steps.last().kind, 'send_failed')


@override_settings(**CREDS)
class RunReadApiTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_user('t', 't@example.com', 'pw'))
        self.tpl, self.root, self.yes, self.no, self.q2, self.a, self.note = build()
        with patch('messaging.services.requests.post') as mock_post:
            mock_post.side_effect = [ok(1), ok(2), ok(3), ok(4)]
            self.client.post(f'/api/templates/{self.tpl.id}/send/',
                             {'phone_numbers': ['919876543210', '919846730362']}, format='json')
            self.client.post('/webhook', json.dumps(tap('919876543210', self.yes, 'wamid.a')),
                             content_type='application/json')

    def test_list_search_by_phone_template_and_status(self):
        get = lambda **p: self.client.get('/api/flow-runs/', p).json()
        self.assertEqual(len(get()), 2)
        self.assertEqual([r['phone_number'] for r in get(q='+91 98467')], ['919846730362'])
        self.assertEqual(len(get(q='surv')), 2)  # template name
        self.assertEqual(len(get(q='nothing-matches')), 0)
        self.assertEqual(len(get(status='active')), 2)
        self.assertEqual(len(get(template=self.tpl.id)), 2)

    def test_detail_has_ordered_steps_flow_and_path(self):
        run = FlowRun.objects.get(phone_number='919876543210')
        d = self.client.get(f'/api/flow-runs/{run.id}/').json()
        self.assertEqual([s['kind'] for s in d['steps']], ['question_sent', 'option_tapped', 'question_sent'])
        self.assertEqual(d['flow']['root']['text'], 'Member?')
        self.assertEqual(d['path']['option_ids'], [self.yes.id])
        self.assertIn(self.q2.id, d['path']['question_ids'])
        self.assertEqual(d['run']['current_question_id'], self.q2.id)

    def test_detail_survives_template_deletion(self):
        run = FlowRun.objects.get(phone_number='919876543210')
        self.tpl.delete()
        d = self.client.get(f'/api/flow-runs/{run.id}/').json()
        self.assertIsNone(d['flow'])
        self.assertEqual(d['run']['template']['name'], 'Survey')
        self.assertEqual(len(d['steps']), 3)  # the recorded journey is kept

    def test_template_stats(self):
        s = self.client.get(f'/api/templates/{self.tpl.id}/stats/').json()
        self.assertEqual((s['runs'], s['active'], s['completed'], s['failed']), (2, 2, 0, 0))
        self.assertEqual(s['users_here'][str(self.root.id)], 1)  # the person who has not answered yet
        self.assertEqual(s['users_here'][str(self.q2.id)], 1)    # the person who tapped "yes"
        self.assertEqual(s['option_taps'], {str(self.yes.id): 1})
        self.assertEqual(s['reached'][str(self.root.id)], 2)

    def test_history_shows_template_and_can_filter_by_it(self):
        rows = self.client.get('/api/messages/').json()
        self.assertTrue(all(r['template']['name'] == 'Survey' for r in rows))
        other = MessageTemplate.objects.create(name='Other', description='d')
        self.assertEqual(self.client.get('/api/messages/', {'template': other.id}).json(), [])
        self.assertTrue(len(self.client.get('/api/messages/', {'template': self.tpl.id}).json()) > 0)

    def test_endpoints_need_login(self):
        self.client.force_authenticate(user=None)
        for url in ['/api/flow-runs/', '/api/flow-runs/1/', f'/api/templates/{self.tpl.id}/stats/']:
            self.assertEqual(self.client.get(url).status_code, 401, url)
