from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import MessageTemplate, Option, Question


class QuestionWithOptionsTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=User.objects.create_user('t', 't@example.com', 'pw'))
        self.tpl = MessageTemplate.objects.create(name='Survey', description='d')
        self.url = f'/api/templates/{self.tpl.id}/questions/'

    def post(self, body):
        return self.client.post(self.url, body, format='json')

    def test_creates_question_and_options_together(self):
        r = self.post({'text': 'Pick', 'options': ['  one ', 'two', 'three']})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(
            list(Option.objects.filter(question_id=r.json()['id']).values_list('title', flat=True)),
            ['one', 'two', 'three'],
        )

    def test_options_are_optional(self):
        self.assertEqual(self.post({'text': 'Alone'}).status_code, 201)
        self.assertEqual(Option.objects.count(), 0)

    def test_nothing_saved_when_an_option_is_invalid(self):
        bad_bodies = [
            {'text': 'Q', 'options': ['a', 'A']},  # duplicates
            {'text': 'Q', 'options': ['a', '  ']},  # blank
            {'text': 'Q', 'options': ['x' * 21]},  # too long
            {'text': 'Q', 'options': ['a', 'b', 'c', 'd']},  # too many
            {'text': 'Q', 'options': 'abc'},  # not a list
        ]
        for body in bad_bodies:
            self.assertEqual(self.post(body).status_code, 400, body)
        self.assertEqual((Question.objects.count(), Option.objects.count()), (0, 0))

    def test_follow_up_question_with_options(self):
        root = self.post({'text': 'Q1', 'options': ['yes']}).json()
        opt = Option.objects.get(question_id=root['id'])
        r = self.post({'text': 'Q2', 'option_id': opt.id, 'options': ['a', 'b']})
        self.assertEqual(r.status_code, 201)
        flow = self.client.get(f'/api/templates/{self.tpl.id}/flow/').json()
        self.assertEqual([o['title'] for o in flow['root']['options'][0]['next']['options']], ['a', 'b'])
