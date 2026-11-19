import json
from unittest.mock import patch

from django.test import TestCase


class HealthEndpointTests(TestCase):
    def test_ok_without_login(self):
        r = self.client.get('/api/health/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'status': 'ok'})

    def test_head_request_works(self):
        self.assertEqual(self.client.head('/api/health/').status_code, 200)

    def test_only_safe_methods(self):
        self.assertEqual(self.client.post('/api/health/').status_code, 405)

    def test_503_when_the_database_check_fails(self):
        with patch('messaging.health.connection.cursor', side_effect=RuntimeError('db is down')):
            r = self.client.get('/api/health/')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {'status': 'unavailable'})
        # the failure reason must not leak to the public
        self.assertNotIn('db is down', r.content.decode())

    def test_exposes_no_configuration_or_paths(self):
        body = json.dumps(self.client.get('/api/health/').json())
        for forbidden in ('sqlite', 'SECRET', 'TOKEN', '/data', 'DEBUG', 'version'):
            self.assertNotIn(forbidden, body)

    def test_not_cacheable(self):
        self.assertIn('no-cache', self.client.get('/api/health/')['Cache-Control'])

    def test_protected_endpoints_still_require_login(self):
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)
        self.assertEqual(self.client.get('/api/messages/').status_code, 401)

    def test_webhook_verification_is_unchanged(self):
        # no verify token supplied -> refused, exactly as before
        self.assertEqual(self.client.get('/webhook').status_code, 403)
