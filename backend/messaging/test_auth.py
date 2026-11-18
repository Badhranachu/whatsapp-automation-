from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APITestCase


class AuthTests(APITestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_superuser('boss@example.com', 'boss@example.com', 'secret-pass-1')

    def login(self, email='boss@example.com', password='secret-pass-1'):
        return self.client.post('/api/auth/login/', {'email': email, 'password': password}, format='json')

    def test_endpoints_require_login(self):
        for url in ['/api/messages/', '/api/stats/', '/api/auth/me/']:
            self.assertEqual(self.client.get(url).status_code, 401, url)
        self.assertEqual(self.client.post('/api/send-message/', {}, format='json').status_code, 401)
        self.assertEqual(self.client.post('/api/send-options/', {}, format='json').status_code, 401)

    def test_login_ok_and_token_works(self):
        r = self.login('BOSS@example.com')  # case-insensitive email
        self.assertEqual(r.status_code, 200)
        token = r.json()['token']
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(self.client.get('/api/auth/me/').json()['email'], 'boss@example.com')
        self.assertEqual(self.client.get('/api/stats/').status_code, 200)

    def test_wrong_password(self):
        self.assertEqual(self.login(password='nope').status_code, 401)
        self.assertEqual(self.login(email='who@example.com').status_code, 401)

    def test_logout_invalidates_token(self):
        token = self.login().json()['token']
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(self.client.post('/api/auth/logout/').status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)

    def test_login_is_rate_limited(self):
        codes = [self.login(password='bad').status_code for _ in range(12)]
        self.assertIn(429, codes)

    def test_webhook_stays_public(self):
        self.assertEqual(self.client.get('/webhook').status_code, 403)  # reachable, just fails verification
