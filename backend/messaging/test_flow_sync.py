from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import AuditLog, MessageTemplate, Option, Question

FLOW = {
    'text': 'Use the app?',
    'options': [
        {'title': 'Yes', 'next': {'text': 'How often?', 'options': [
            {'title': 'Daily', 'next': {'text': 'Great'}},
            {'title': 'Weekly', 'next': {'text': 'Thanks'}},
        ]}},
        {'title': 'No', 'next': {'text': 'Bye'}},
    ],
}


def strip_depth(node):
    """Shape of the flow JSON box: ids kept, depth dropped."""
    out = {'id': node['id'], 'text': node['text']}
    if node['options']:
        out['options'] = [
            {'id': o['id'], 'title': o['title'], **({'next': strip_depth(o['next'])} if o['next'] else {})}
            for o in node['options']
        ]
    return out


class FlowSyncTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_superuser('boss', 'b@example.com', 'pw-12345-x'))
        self.tpl = MessageTemplate.objects.create(name='S')
        self.url = f'/api/templates/{self.tpl.id}/sync-flow/'
        self.client.post(f'/api/templates/{self.tpl.id}/import-flow/', FLOW, format='json')

    def current(self):
        return strip_depth(self.client.get(f'/api/templates/{self.tpl.id}/flow/').json()['root'])

    def test_round_trip_changes_nothing(self):
        before = (Question.objects.count(), Option.objects.count())
        r = self.client.post(self.url, self.current(), format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['changes'], {'created_questions': 0, 'updated_questions': 0, 'created_options': 0, 'updated_options': 0})
        self.assertEqual((Question.objects.count(), Option.objects.count()), before)

    def test_ids_update_in_place_without_creating(self):
        flow = self.current()
        root_id, yes_id = flow['id'], flow['options'][0]['id']
        flow['text'] = 'Do you use the app?'
        flow['options'][0]['title'] = 'Yes!'
        flow['options'][0]['next']['options'][0]['next']['text'] = 'Wonderful'
        before = (Question.objects.count(), Option.objects.count())
        r = self.client.post(self.url, flow, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((Question.objects.count(), Option.objects.count()), before)
        self.assertEqual(Question.objects.get(pk=root_id).text, 'Do you use the app?')
        self.assertEqual(Option.objects.get(pk=yes_id).title, 'Yes!')
        self.assertEqual(r.json()['changes']['updated_questions'], 2)
        self.assertEqual(r.json()['changes']['updated_options'], 1)
        self.assertTrue(AuditLog.objects.filter(action='update', entity_type='flow').exists())

    def test_no_id_adds_new_and_omitted_items_are_kept(self):
        flow = self.current()
        flow['options'] = [flow['options'][0]]  # leave "No" out: it must not be deleted
        flow['options'][0]['next']['options'].append({'title': 'Monthly', 'next': {'text': 'Fine'}})
        r = self.client.post(self.url, flow, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Option.objects.filter(title='No').exists())
        self.assertTrue(Question.objects.filter(text='Fine').exists())

    def test_rejects_bad_input_all_or_nothing(self):
        flow = self.current()
        flow['text'] = 'Changed'
        flow['options'][1]['id'] = 999999  # unknown option id
        r = self.client.post(self.url, flow, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Question.objects.filter(template=self.tpl, parent_option=None).first().text, 'Use the app?')

        for mutate in (
            lambda f: f.update(id=999999),  # root id that is not the saved root
            lambda f: f['options'].extend([{'title': 'x', 'next': {'text': 'y'}}, {'title': 'z', 'next': {'text': 'y'}}]),  # 4 options
            lambda f: f['options'].append({'title': 'yes', 'next': {'text': 'y'}}),  # duplicate of "Yes"
            lambda f: f['options'][0].update(title='x' * 21),
        ):
            f = self.current()
            mutate(f)
            self.assertEqual(self.client.post(self.url, f, format='json').status_code, 400)

    def test_new_option_needs_a_closing_message(self):
        flow = self.current()
        flow['options'][1]['next']['text'] = 'Bye'
        flow['options'][1].pop('next')  # existing option may omit next (keeps its child)
        self.assertEqual(self.client.post(self.url, flow, format='json').status_code, 200)
        flow = self.current()
        flow['options'][0]['next']['options'].append({'title': 'Monthly'})
        r = self.client.post(self.url, flow, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('needs a "next"', r.json()['error'])

    def test_requires_login(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post(self.url, FLOW, format='json').status_code, 401)
