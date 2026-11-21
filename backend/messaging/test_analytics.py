from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import FlowRun, FlowStep, MessageTemplate, Option, Question, add_step


class AnalyticsTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_superuser('t', 't@example.com', 'pw'))
        self.tpl = MessageTemplate.objects.create(name='S')
        self.q = Question.objects.create(template=self.tpl, text='Use it?')
        self.yes = Option.objects.create(question=self.q, title='Yes')
        self.no = Option.objects.create(question=self.q, title='No')
        self.end = Question.objects.create(template=self.tpl, text='Thanks', parent_option=self.yes)

    def run_for(self, phone, tap=None):
        run = FlowRun.objects.create(template=self.tpl, template_name='S', phone_number=phone)
        add_step(run, FlowStep.QUESTION_SENT, question=self.q, text=self.q.text)
        if tap:
            add_step(run, FlowStep.OPTION_TAPPED, option=tap, text=tap.title)
            if tap == self.yes:
                add_step(run, FlowStep.QUESTION_SENT, question=self.end, text='Thanks')
        return run

    def test_funnel_options_routes_and_timeline(self):
        self.run_for('911111111111', self.yes)
        self.run_for('912222222222', self.yes)
        self.run_for('913333333333', self.no)
        self.run_for('914444444444')  # never answered
        data = self.client.get(f'/api/templates/{self.tpl.id}/stats/').json()
        first = data['funnel'][0]
        self.assertEqual((first['reached'], first['answered'], first['drop_off']), (4, 3, 1))
        self.assertEqual(first['drop_off_pct'], 25.0)
        self.assertEqual({o['title']: o['share_pct'] for o in first['options']}, {'Yes': 66.7, 'No': 33.3})
        end = data['funnel'][1]
        self.assertTrue(end['is_end_note'])
        self.assertEqual((end['reached'], end['drop_off']), (2, 0))
        self.assertEqual(data['top_routes'][0], {'route': 'Yes', 'count': 2})
        self.assertEqual(data['timeline'][0]['sends'], 4)

    def test_date_filter_and_export(self):
        self.run_for('911111111111', self.yes)
        url = f'/api/templates/{self.tpl.id}/stats/'
        self.assertEqual(self.client.get(url, {'from': '2999-01-01'}).json()['runs'], 0)
        self.assertEqual(self.client.get(url, {'from': '2000-01-01', 'to': '2999-01-01'}).json()['runs'], 1)
        r = self.client.get(f'/api/templates/{self.tpl.id}/export/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('+911111111111', r.content.decode())
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(f'/api/templates/{self.tpl.id}/export/').status_code, 401)
