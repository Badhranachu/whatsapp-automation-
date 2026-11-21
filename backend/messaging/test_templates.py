from django.contrib.auth.models import User
from rest_framework.test import APITestCase


class TemplateTests(APITestCase):
    def authed(self):
        self.client.force_authenticate(user=User.objects.create_superuser('t', 't@example.com', 'pw'))

    def test_requires_login(self):
        self.assertEqual(self.client.get('/api/templates/').status_code, 401)
        self.assertEqual(self.client.post('/api/templates/', {}, format='json').status_code, 401)

    def test_create_and_list_newest_first(self):
        self.authed()
        r1 = self.client.post('/api/templates/', {'name': ' First ', 'description': 'one'}, format='json')
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r1.json()['name'], 'First')  # trimmed
        self.client.post('/api/templates/', {'name': 'Second', 'description': 'two'}, format='json')
        names = [t['name'] for t in self.client.get('/api/templates/').json()]
        self.assertEqual(names, ['Second', 'First'])

    def test_name_required(self):
        self.authed()
        for bad in [{'name': '', 'description': 'x'}, {'description': 'x'},
                    {'name': '   ', 'description': 'x'}, {'name': ''}]:
            self.assertEqual(self.client.post('/api/templates/', bad, format='json').status_code, 400, bad)

    def test_description_optional(self):
        self.authed()
        for payload in [{'name': 'a'}, {'name': 'b', 'description': ''}, {'name': 'c', 'description': '  '}]:
            r = self.client.post('/api/templates/', payload, format='json')
            self.assertEqual(r.status_code, 201, payload)
            self.assertEqual(r.json()['description'], '')
