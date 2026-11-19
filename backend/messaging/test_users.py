from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

GOOD = {
    'email': 'New.Admin@Example.com',
    'phone_number': '+91 98765 43210',
    'password': 'Str0ng-pass-phrase-77',
    'confirm_password': 'Str0ng-pass-phrase-77',
}


class UserManagementTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser('admin@example.com', 'admin@example.com', 'AdminPass-12345')
        self.client.force_authenticate(self.admin)

    def test_requires_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/users/').status_code, 401)

    def test_non_superuser_is_forbidden(self):
        staff = User.objects.create_user('s@example.com', 's@example.com', 'x-Pass-12345')
        self.client.force_authenticate(staff)
        self.assertEqual(self.client.get('/api/users/').status_code, 403)
        self.assertEqual(self.client.post('/api/users/', GOOD, format='json').status_code, 403)
        self.assertFalse(User.objects.filter(email='new.admin@example.com').exists())

    def test_create_super_admin_who_can_log_in(self):
        res = self.client.post('/api/users/', GOOD, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['user']['phone_number'], '919876543210')
        self.assertNotIn('password', str(res.data))
        user = User.objects.get(email='new.admin@example.com')
        self.assertTrue(user.is_superuser and user.is_staff)
        self.client.force_authenticate(None)
        login = self.client.post('/api/auth/login/', {'email': 'NEW.admin@example.com', 'password': GOOD['password']}, format='json')
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.data['is_superuser'])

    def test_password_mismatch(self):
        res = self.client.post('/api/users/', {**GOOD, 'confirm_password': 'different'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('confirm_password', res.data['error'])

    def test_weak_password_rejected(self):
        res = self.client.post('/api/users/', {**GOOD, 'password': '12345678', 'confirm_password': '12345678'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('password', res.data['error'])

    def test_bad_email_and_phone(self):
        self.assertEqual(self.client.post('/api/users/', {**GOOD, 'email': 'nope'}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/users/', {**GOOD, 'phone_number': '12'}, format='json').status_code, 400)

    def test_duplicate_email_any_case(self):
        res = self.client.post('/api/users/', {**GOOD, 'email': 'ADMIN@example.com'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(User.objects.count(), 1)

    def test_list_includes_profile_without_secrets(self):
        self.client.post('/api/users/', GOOD, format='json')
        res = self.client.get('/api/users/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 2)
        self.assertNotIn('password', str(res.data))
        self.assertEqual(res.data[0]['phone_number'], '')  # the original admin has no profile

    def test_me_reports_role(self):
        self.assertTrue(self.client.get('/api/auth/me/').data['is_superuser'])

    def test_delete_needs_password_and_not_self(self):
        self.client.post('/api/users/', GOOD, format='json')
        other = User.objects.get(email='new.admin@example.com')
        Token.objects.create(user=other)
        url = f'/api/users/{other.id}/'
        self.assertEqual(self.client.delete(url, {'password': 'wrong'}, format='json').status_code, 403)
        self.assertEqual(self.client.delete(url, {}, format='json').status_code, 403)
        self.assertTrue(User.objects.filter(pk=other.pk).exists())
        me = f'/api/users/{self.admin.id}/'
        self.assertEqual(self.client.delete(me, {'password': 'AdminPass-12345'}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(url, {'password': 'AdminPass-12345'}, format='json').status_code, 204)
        self.assertFalse(User.objects.filter(pk=other.pk).exists())
        self.assertFalse(Token.objects.filter(user_id=other.pk).exists())
