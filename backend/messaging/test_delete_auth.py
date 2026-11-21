from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APITestCase

from .models import MessageTemplate, Option, Question


class TemplateDeleteNeedsAdminPasswordTests(APITestCase):
    def setUp(self):
        cache.clear()  # the delete throttle counts attempts across tests otherwise
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'admin-pass-1')
        self.staff = User.objects.create_user('staff', 'staff@example.com', 'staff-pass-1')
        self.tpl = MessageTemplate.objects.create(name='Survey', description='d')
        q = Question.objects.create(template=self.tpl, text='Q?')
        Option.objects.create(question=q, title='yes')
        self.url = f'/api/templates/{self.tpl.id}/'

    def delete(self, user, password=None):
        self.client.force_authenticate(user=user)
        body = {} if password is None else {'password': password}
        return self.client.delete(self.url, body, format='json')

    def still_there(self):
        return MessageTemplate.objects.filter(pk=self.tpl.pk).exists()

    def test_correct_password_deletes_template_and_questions(self):
        self.assertEqual(self.delete(self.admin, 'admin-pass-1').status_code, 204)
        self.assertFalse(self.still_there())
        self.assertEqual((Question.objects.count(), Option.objects.count()), (0, 0))

    def test_wrong_or_missing_password_deletes_nothing(self):
        for password in ['nope', '', None]:
            r = self.delete(self.admin, password)
            self.assertEqual(r.status_code, 403, password)
            self.assertIn('Nothing was deleted', r.json()['error'])
        self.assertTrue(self.still_there())

    def test_a_non_superuser_cannot_delete_even_with_their_own_password(self):
        self.assertEqual(self.delete(self.staff, 'staff-pass-1').status_code, 403)
        self.assertTrue(self.still_there())

    def test_cannot_use_another_users_password(self):
        # logged in as staff but typing the admin's password is still refused
        self.assertEqual(self.delete(self.staff, 'admin-pass-1').status_code, 403)
        self.assertTrue(self.still_there())

    def test_password_guessing_is_rate_limited(self):
        codes = [self.delete(self.admin, f'guess-{i}').status_code for i in range(8)]
        self.assertIn(429, codes)
        # once limited, even the right password is refused for now
        self.assertEqual(self.delete(self.admin, 'admin-pass-1').status_code, 429)
        self.assertTrue(self.still_there())

    def test_reading_and_editing_do_not_need_the_password(self):
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        r = self.client.patch(self.url, {'name': 'Renamed'}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_a_non_superuser_cannot_even_read_or_edit(self):
        self.client.force_authenticate(user=self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.patch(self.url, {'name': 'Renamed'}, format='json').status_code, 403)
        self.assertEqual(MessageTemplate.objects.get(pk=self.tpl.pk).name, 'Survey')

    def test_wrong_password_is_not_a_401(self):
        # a 401 would make the web page log the user out
        self.assertNotEqual(self.delete(self.admin, 'nope').status_code, 401)
