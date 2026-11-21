from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import MessageTemplate, Option, Question

FLOW = {
    'text': 'Use the app?',
    'options': [
        {'title': 'Yes', 'next': {'text': 'How often?', 'options': [{'title': 'Daily', 'next': {'text': 'Great'}}, {'title': 'Weekly', 'next': {'text': 'Thanks'}}]}},
        {'title': 'No', 'next': {'text': 'Bye'}},
    ],
}


class FlowImportTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_superuser('t', 't@example.com', 'pw'))
        self.tpl = MessageTemplate.objects.create(name='S')
        self.url = f'/api/templates/{self.tpl.id}/import-flow/'

    def test_imports_nested_flow_with_end_notes(self):
        r = self.client.post(self.url, FLOW, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['stats'], {'questions': 5, 'options': 4, 'depth': 3})
        end = Question.objects.get(text='Bye')
        self.assertEqual(end.options.count(), 0)

    def test_invalid_is_all_or_nothing(self):
        bad = {'text': 'Q', 'options': [{'title': 'ok', 'next': {'text': 'fine'}}, {'title': 'x' * 21}]}
        r = self.client.post(self.url, bad, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual((Question.objects.count(), Option.objects.count()), (0, 0))

    def test_rejects_bad_shapes(self):
        for bad in [{}, {'text': 'Q', 'options': [{'title': 'a', 'next': {'text': 'x'}}, {'title': 'A', 'next': {'text': 'y'}}]}, {'text': 'Q', 'options': [{'title': t, 'next': {'text': 'z'}} for t in 'abcd']},
                    {'text': 'Q', 'options': 'x'}, {'text': 'Q', 'options': [{'next': {'text': 'z'}}]},
                    {'text': 'Q', 'options': ['plain']}, {'text': 'Q', 'options': [{'title': 'no closing'}]}]:
            self.assertEqual(self.client.post(self.url, bad, format='json').status_code, 400, bad)

    def test_only_when_template_empty(self):
        self.assertEqual(self.client.post(self.url, FLOW, format='json').status_code, 201)
        self.assertEqual(self.client.post(self.url, FLOW, format='json').status_code, 400)

    def test_requires_login(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post(self.url, FLOW, format='json').status_code, 401)
