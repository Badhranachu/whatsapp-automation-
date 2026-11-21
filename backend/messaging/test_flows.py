from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import MessageTemplate, Option, Question


class FlowTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_superuser('t', 't@example.com', 'pw'))
        self.tpl = MessageTemplate.objects.create(name='Survey', description='d')

    def add_question(self, text, option_id=None, tpl=None):
        body = {'text': text}
        if option_id:
            body['option_id'] = option_id
        return self.client.post(f'/api/templates/{(tpl or self.tpl).id}/questions/', body, format='json')

    def add_option(self, qid, title):
        return self.client.post(f'/api/questions/{qid}/options/', {'title': title}, format='json')

    def flow(self):
        return self.client.get(f'/api/templates/{self.tpl.id}/flow/').json()

    def test_requires_login(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(f'/api/templates/{self.tpl.id}/flow/').status_code, 401)

    def test_empty_flow(self):
        f = self.flow()
        self.assertIsNone(f['root'])
        self.assertEqual(f['stats'], {'questions': 0, 'options': 0, 'depth': 0})

    def test_build_nested_flow_of_any_depth(self):
        q = self.add_question('Are you ready?').json()
        for depth in range(2, 8):  # keep nesting under the first option each time
            o = self.add_option(q['id'], 'yes').json()
            q = self.add_question(f'Level {depth}', option_id=o['id']).json()
        f = self.flow()
        self.assertEqual(f['stats']['depth'], 7)
        self.assertEqual(f['stats']['questions'], 7)
        node = f['root']
        for _ in range(6):
            node = node['options'][0]['next']
        self.assertEqual(node['text'], 'Level 7')

    def test_branching(self):
        q = self.add_question('Pick one').json()
        a = self.add_option(q['id'], 'A').json()
        self.add_option(q['id'], 'B')
        self.add_question('After A', option_id=a['id'])
        root = self.flow()['root']
        self.assertEqual([o['title'] for o in root['options']], ['A', 'B'])
        self.assertEqual(root['options'][0]['next']['text'], 'After A')
        self.assertIsNone(root['options'][1]['next'])

    def test_only_one_root(self):
        self.assertEqual(self.add_question('First').status_code, 201)
        self.assertEqual(self.add_question('Second').status_code, 400)

    def test_option_leads_to_only_one_question(self):
        q = self.add_question('Q').json()
        o = self.add_option(q['id'], 'x').json()
        self.assertEqual(self.add_question('n1', option_id=o['id']).status_code, 201)
        self.assertEqual(self.add_question('n2', option_id=o['id']).status_code, 400)

    def test_option_limits(self):
        q = self.add_question('Q').json()
        self.assertEqual(self.add_option(q['id'], 'x' * 21).status_code, 400)  # >20 chars
        self.assertEqual(self.add_option(q['id'], '  ').status_code, 400)
        for t in ['one', 'two', 'three']:
            self.assertEqual(self.add_option(q['id'], t).status_code, 201)
        self.assertEqual(self.add_option(q['id'], 'four').status_code, 400)  # max 3

    def test_duplicate_option_rejected(self):
        q = self.add_question('Q').json()
        self.add_option(q['id'], 'Yes')
        self.assertEqual(self.add_option(q['id'], 'yes').status_code, 400)

    def test_option_from_another_template_rejected(self):
        other = MessageTemplate.objects.create(name='Other', description='d')
        q = self.add_question('Q').json()
        o = self.add_option(q['id'], 'x').json()
        self.assertEqual(self.add_question('bad', option_id=o['id'], tpl=other).status_code, 404)

    def test_delete_option_removes_its_subtree(self):
        q = self.add_question('Q').json()
        o = self.add_option(q['id'], 'x').json()
        self.add_question('child', option_id=o['id'])
        self.assertEqual(self.client.delete(f"/api/options/{o['id']}/").status_code, 204)
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(Option.objects.count(), 0)

    def test_delete_question_removes_everything_below(self):
        q = self.add_question('Q').json()
        o = self.add_option(q['id'], 'x').json()
        self.add_question('child', option_id=o['id'])
        self.assertEqual(self.client.delete(f"/api/questions/{q['id']}/").status_code, 204)
        self.assertEqual((Question.objects.count(), Option.objects.count()), (0, 0))
        self.assertIsNone(self.flow()['root'])

    def test_template_list_shows_question_count(self):
        self.add_question('Q')
        data = self.client.get('/api/templates/').json()
        self.assertEqual(data[0]['question_count'], 1)
