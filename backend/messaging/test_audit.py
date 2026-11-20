from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import AuditLog


class AuditTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'admin-pass-1')
        self.client.force_authenticate(user=self.admin)

    def test_template_lifecycle_is_logged_with_actor_and_role(self):
        r = self.client.post('/api/templates/', {'name': 'A', 'description': 'one'}, format='json')
        tid = r.json()['id']
        self.client.patch(f'/api/templates/{tid}/', {'name': 'B'}, format='json')
        self.client.delete(f'/api/templates/{tid}/', {'password': 'admin-pass-1'}, format='json')
        rows = list(AuditLog.objects.order_by('id').values_list('action', 'entity_type', 'actor_email', 'actor_role'))
        self.assertEqual(rows, [('create', 'template', 'boss@example.com', 'super_admin')] * 0 + [
            ('create', 'template', 'boss@example.com', 'super_admin'),
            ('update', 'template', 'boss@example.com', 'super_admin'),
            ('delete', 'template', 'boss@example.com', 'super_admin'),
        ])
        update = AuditLog.objects.get(action='update')
        self.assertEqual(update.changes, {'name': {'from': 'A', 'to': 'B'}})

    def test_flow_edits_are_logged(self):
        tid = self.client.post('/api/templates/', {'name': 'A'}, format='json').json()['id']
        self.client.post(f'/api/templates/{tid}/import-flow/', {'text': 'Q', 'options': [{'title': 'x', 'next': {'text': 'Bye'}}]}, format='json')
        self.assertTrue(AuditLog.objects.filter(action='import', entity_type='flow').exists())

    def test_login_and_failed_login_logged_without_password(self):
        self.client.force_authenticate(user=None)
        self.client.post('/api/auth/login/', {'email': 'boss@example.com', 'password': 'nope'}, format='json')
        self.client.post('/api/auth/login/', {'email': 'boss@example.com', 'password': 'admin-pass-1'}, format='json')
        actions = set(AuditLog.objects.values_list('action', flat=True))
        self.assertTrue({'login', 'login_failed'} <= actions)
        self.assertNotIn('admin-pass-1', str(list(AuditLog.objects.values())))

    def test_only_super_admin_can_read(self):
        self.client.post('/api/templates/', {'name': 'A'}, format='json')
        self.assertEqual(len(self.client.get('/api/audit-logs/').json()), 1)
        self.assertEqual(len(self.client.get('/api/audit-logs/?entity=user').json()), 0)
        staff = User.objects.create_user('s', 's@example.com', 'pw')
        self.client.force_authenticate(user=staff)
        self.assertEqual(self.client.get('/api/audit-logs/').status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get('/api/audit-logs/').status_code, 401)
