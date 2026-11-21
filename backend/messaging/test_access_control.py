"""The whole API is for active super admins only.

These tests discover EVERY route by themselves (so a route added later is covered too) and check, for each HTTP
method it supports, what an anonymous caller, a bad token, an ordinary user, an inactive super admin, a demoted
admin and a real super admin each get. Rejected calls must change nothing and contact no outside service.

Set PRINT_ACCESS_TABLE=1 to print the table of results.
"""
import hashlib
import hmac
import json
import os
import re
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.contrib.auth.models import User
from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import URLResolver, get_resolver
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from .login_otp import CHALLENGE_SALT
from .models import FlowRun, MessageLog, MessageTemplate, Option, Question
from .permissions import IsSuperAdmin

# Reachable before anyone is signed in, on purpose. Everything else must demand a super admin.
PUBLIC_API = {
    'api/health/': 'health check (no data)',
    'api/auth/login/': 'sign-in step 1 (only super admins get a session)',
    'api/auth/login/verify/': 'sign-in step 2 (needs the signed challenge from step 1)',
    'api/auth/login/resend/': 'sign-in code resend (needs the signed challenge from step 1)',
}
DENIED_DETAIL = 'Super admin access is required.'
BODY_METHODS = {'post', 'put', 'patch', 'delete'}


def discover_routes():
    """[(route, view_class)] for every URL, however deeply it is included."""
    found = []

    def walk(patterns, prefix=''):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, prefix + str(p.pattern))
            else:
                found.append((prefix + str(p.pattern), p.callback))

    walk(get_resolver().url_patterns)
    out = []
    for route, callback in found:
        cls = getattr(callback, 'cls', None) or getattr(callback, 'view_class', None)
        out.append((route, cls, callback))
    return out


def api_routes():
    """Application API routes that are not on the public list (and not the Django admin or the webhook)."""
    return [
        (route, cls) for route, cls, _ in discover_routes()
        if route.startswith('api/') and route not in PUBLIC_API and cls is not None
    ]


def concrete(route):
    return '/' + re.sub(r'<[^>]+>', '1', route)


def methods_of(cls):
    return [m for m in cls.http_method_names if m not in ('options', 'head', 'trace') and hasattr(cls, m)]


def snapshot():
    """Row counts of every table of this app plus users and tokens: rejected calls must leave them unchanged."""
    models = list(apps.get_app_config('messaging').get_models()) + [User, Token]
    return {m.__name__: m.objects.count() for m in models}


class AccessControlBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.root = User.objects.create_superuser('root@example.com', 'root@example.com', 'root-pass-12345')
        self.normal = User.objects.create_user('normal@example.com', 'normal@example.com', 'normal-pass-12345')
        self.inactive_root = User.objects.create_superuser('gone@example.com', 'gone@example.com', 'gone-pass-12345')
        self.demoted = User.objects.create_superuser('demoted@example.com', 'demoted@example.com', 'demoted-pass-12345')
        self.tokens = {u.email: Token.objects.create(user=u).key for u in (self.root, self.normal, self.inactive_root, self.demoted)}
        # the tokens existed while the accounts were fine; now the accounts change
        User.objects.filter(pk=self.inactive_root.pk).update(is_active=False)
        User.objects.filter(pk=self.demoted.pk).update(is_superuser=False)

        tpl = MessageTemplate.objects.create(name='Private survey', description='secret plan')
        q = Question.objects.create(template=tpl, text='Question?')
        Option.objects.create(question=q, title='Yes')
        MessageLog.objects.create(direction='out', phone_number='919800011122', message_type='flow', content='private text')
        FlowRun.objects.create(template=tpl, template_name=tpl.name, phone_number='919800011122')

    def client_for(self, who):
        # a previous call in a sweep may have been "log out"; make sure the account's token exists again
        if who in self.tokens:
            Token.objects.get_or_create(user=User.objects.get(email=who), defaults={'key': self.tokens[who]})
        c = APIClient()
        if who == 'bad-token':
            c.credentials(HTTP_AUTHORIZATION='Token not-a-real-token-0123456789')
        elif who != 'anonymous':
            c.credentials(HTTP_AUTHORIZATION=f'Token {self.tokens[who]}')
        return c

    @staticmethod
    def call(client, method, path):
        if method in BODY_METHODS:
            return client.generic(method.upper(), path, data=json.dumps({'is_superuser': True, 'role': 'admin'}), content_type='application/json')
        return client.generic(method.upper(), path)


class EveryRouteIsSuperAdminOnlyTests(AccessControlBase):
    def test_discovery_found_the_routes(self):
        routes = api_routes()
        self.assertGreaterEqual(len(routes), 25, 'route discovery looks broken')
        paths = {r for r, _ in routes}
        for expected in ('api/messages/', 'api/send-message/', 'api/templates/', 'api/users/', 'api/audit-logs/',
                         'api/profile/', 'api/templates/<int:template_id>/export/'):
            self.assertIn(expected, paths)

    def test_every_protected_view_uses_the_super_admin_rule(self):
        """A static guard: no view may override the default with something weaker."""
        for route, cls in api_routes():
            self.assertTrue(
                any(issubclass(pc, IsSuperAdmin) for pc in cls.permission_classes),
                f'{route} ({cls.__name__}) is not protected by IsSuperAdmin: {cls.permission_classes}',
            )

    def test_rejected_callers_get_401_or_403_change_nothing_and_reach_no_outside_service(self):
        expected = {'anonymous': 401, 'bad-token': 401, 'gone@example.com': 401, 'normal@example.com': 403, 'demoted@example.com': 403}
        checked = 0
        with patch('messaging.services.requests.post') as outbound, patch('messaging.services.requests.get') as outbound_get:
            before = snapshot()
            for route, cls in api_routes():
                for method in methods_of(cls):
                    for who, want in expected.items():
                        r = self.call(self.client_for(who), method, concrete(route))
                        self.assertEqual(r.status_code, want, f'{method.upper()} {route} as {who}: {r.status_code} {r.content[:120]}')
                        checked += 1
            self.assertEqual(snapshot(), before, 'a rejected request changed the database')
            outbound.assert_not_called()
            outbound_get.assert_not_called()
        self.assertGreater(checked, 150)

    def test_a_real_super_admin_is_let_in_everywhere(self):
        fake = MagicMock(status_code=200)
        fake.json.return_value = {'messages': [{'id': 'wamid.test'}]}
        with patch('messaging.services.requests.post', return_value=fake):
            for route, cls in api_routes():
                for method in methods_of(cls):
                    r = self.call(self.client_for('root@example.com'), method, concrete(route))
                    denied = r.status_code == 401 or (r.status_code == 403 and r.json().get('detail') == DENIED_DETAIL)
                    self.assertFalse(denied, f'{method.upper()} {route} refused a super admin: {r.status_code} {r.content[:120]}')

    def test_print_the_table(self):
        if not os.environ.get('PRINT_ACCESS_TABLE'):
            self.skipTest('set PRINT_ACCESS_TABLE=1 to print the table')
        fake = MagicMock(status_code=200)
        fake.json.return_value = {'messages': [{'id': 'wamid.test'}]}
        rows = []
        with patch('messaging.services.requests.post', return_value=fake):
            for route, cls in sorted(api_routes()):
                for method in methods_of(cls):
                    cells = [self.call(self.client_for(w), method, concrete(route)).status_code
                             for w in ('anonymous', 'normal@example.com', 'root@example.com')]
                    rows.append(f'| {method.upper()} | /{route} | {cells[0]} | {cells[1]} | {cells[2]} |')
        print('\n| Method | Route | Anonymous | Normal user | Super admin |\n|---|---|---|---|---|\n' + '\n'.join(rows))


class DataStaysPrivateTests(AccessControlBase):
    def test_no_private_data_in_any_refusal(self):
        for who in ('anonymous', 'normal@example.com', 'demoted@example.com', 'bad-token'):
            c = self.client_for(who)
            for path in ('/api/messages/', '/api/flow-runs/', '/api/templates/', '/api/stats/', '/api/users/', '/api/audit-logs/'):
                body = c.get(path).content.decode()
                for secret in ('919800011122', 'private text', 'Private survey', 'secret plan', 'root@example.com'):
                    self.assertNotIn(secret, body, f'{path} leaked {secret!r} to {who}')

    def test_a_normal_user_cannot_send_or_change_or_delete_anything(self):
        c = self.client_for('normal@example.com')
        tpl = MessageTemplate.objects.get()
        q = Question.objects.get()
        o = Option.objects.get()
        with patch('messaging.services.requests.post') as outbound:
            self.assertEqual(c.post('/api/send-message/', {'phone_number': '9876543210'}, format='json').status_code, 403)
            self.assertEqual(c.post(f'/api/templates/{tpl.id}/send/', {'phone_numbers': ['9876543210']}, format='json').status_code, 403)
            self.assertEqual(c.patch(f'/api/templates/{tpl.id}/', {'name': 'x'}, format='json').status_code, 403)
            self.assertEqual(c.delete(f'/api/questions/{q.id}/').status_code, 403)
            self.assertEqual(c.delete(f'/api/options/{o.id}/').status_code, 403)
            self.assertEqual(c.post(f'/api/templates/{tpl.id}/sync-flow/', {'text': 'x'}, format='json').status_code, 403)
            self.assertEqual(c.get(f'/api/templates/{tpl.id}/export/').status_code, 403)
            self.assertEqual(c.post('/api/users/', {'email': 'new@example.com'}, format='json').status_code, 403)
            outbound.assert_not_called()
        tpl.refresh_from_db()
        self.assertEqual(tpl.name, 'Private survey')
        self.assertTrue(Question.objects.filter(pk=q.pk).exists() and Option.objects.filter(pk=o.pk).exists())

    def test_claiming_to_be_an_admin_in_a_request_does_nothing(self):
        c = self.client_for('normal@example.com')
        for body in ({'is_superuser': True}, {'is_staff': True, 'role': 'admin', 'is_admin': True}):
            self.assertEqual(c.patch('/api/profile/', body, format='json').status_code, 403)
            self.assertEqual(c.post('/api/users/', {**body, 'email': 'x@example.com'}, format='json').status_code, 403)
        r = APIClient()
        r.credentials(HTTP_AUTHORIZATION=f'Token {self.tokens["normal@example.com"]}', HTTP_X_ROLE='admin', HTTP_X_IS_SUPERUSER='true')
        self.assertEqual(r.get('/api/messages/').status_code, 403)
        self.normal.refresh_from_db()
        self.assertFalse(self.normal.is_superuser or self.normal.is_staff)

    def test_the_role_is_read_from_the_database_on_every_request(self):
        """A token from before a demotion stops working at once; one from before a deactivation is rejected too."""
        c = self.client_for('root@example.com')
        self.assertEqual(c.get('/api/stats/').status_code, 200)
        User.objects.filter(pk=self.root.pk).update(is_superuser=False)
        self.assertEqual(c.get('/api/stats/').status_code, 403)
        User.objects.filter(pk=self.root.pk).update(is_superuser=True, is_active=False)
        self.assertEqual(c.get('/api/stats/').status_code, 401)

    def test_an_email_address_alone_proves_nothing(self):
        impostor = User.objects.create_user('root2@example.com', 'ROOT@example.com', 'impostor-pass-12345')
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=impostor).key}')
        self.assertEqual(c.get('/api/stats/').status_code, 403)


@override_settings(LOGIN_OTP_REQUIRED=False, MPIN='')
class SignInIsForSuperAdminsOnlyTests(AccessControlBase):
    def login(self, email, password):
        return APIClient().post('/api/auth/login/', {'email': email, 'password': password}, format='json')

    def test_a_super_admin_gets_a_token_that_works(self):
        r = self.login('root@example.com', 'root-pass-12345')
        self.assertEqual(r.status_code, 200, r.content)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Token {r.json()["token"]}')
        self.assertEqual(c.get('/api/stats/').status_code, 200)

    def test_a_normal_user_with_the_right_password_gets_no_session(self):
        wrong = self.login('normal@example.com', 'not-the-password')
        right = self.login('normal@example.com', 'normal-pass-12345')
        self.assertEqual((wrong.status_code, right.status_code), (401, 401))
        self.assertEqual(wrong.json(), right.json())  # indistinguishable from a wrong password
        self.assertNotIn('token', right.json())
        Token.objects.filter(user=self.normal).delete()
        self.login('normal@example.com', 'normal-pass-12345')
        self.assertFalse(Token.objects.filter(user=self.normal).exists())

    def test_inactive_and_demoted_admins_cannot_sign_in(self):
        self.assertEqual(self.login('gone@example.com', 'gone-pass-12345').status_code, 401)
        self.assertEqual(self.login('demoted@example.com', 'demoted-pass-12345').status_code, 401)

    @override_settings(LOGIN_OTP_REQUIRED=True, OTP_EMAIL_ASYNC=False)
    def test_with_the_extra_step_on_a_normal_user_never_gets_a_challenge_or_token(self):
        r = self.login('normal@example.com', 'normal-pass-12345')
        self.assertEqual(r.status_code, 401)
        self.assertNotIn('challenge', r.json())

    @override_settings(LOGIN_OTP_REQUIRED=True, MPIN='4829')
    def test_a_forged_challenge_for_a_normal_user_is_useless(self):
        forged = signing.dumps({'uid': self.normal.id}, salt=CHALLENGE_SALT)  # signed correctly, but not a super admin
        for typed in ('123456', '330a4829123'):
            r = APIClient().post('/api/auth/login/verify/', {'challenge': forged, 'otp': typed}, format='json')
            self.assertEqual(r.status_code, 400)
            self.assertNotIn('token', r.json())
        self.assertFalse(Token.objects.filter(user=self.normal, key__isnull=False).exclude(key=self.tokens['normal@example.com']).exists())


APP_SECRET = 'meta-app-secret-for-tests'
HOOK = {'entry': [{'changes': [{'value': {'messages': [{'from': '919800011122', 'id': 'wamid.in1', 'type': 'text', 'text': {'body': 'hello'}}]}}]}]}


def signed(body_bytes, secret=APP_SECRET):
    return 'sha256=' + hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


@override_settings(WHATSAPP_APP_SECRET=APP_SECRET, WHATSAPP_VERIFY_TOKEN='verify-me', WHATSAPP_ACCESS_TOKEN='t',
                   WHATSAPP_PHONE_NUMBER_ID='1', WEBHOOK_ALLOW_UNSIGNED=False)
class WebhookAndPublicEndpointTests(TestCase):
    def post(self, body=None, signature=None):
        raw = json.dumps(HOOK if body is None else body).encode()
        extra = {} if signature is None else {'HTTP_X_HUB_SIGNATURE_256': signature(raw) if callable(signature) else signature}
        return self.client.post('/webhook', raw, content_type='application/json', **extra)

    def assert_nothing_happened(self, outbound):
        self.assertEqual((MessageLog.objects.count(), FlowRun.objects.count()), (0, 0))
        outbound.assert_not_called()

    def test_a_correctly_signed_request_is_accepted_and_recorded(self):
        with patch('messaging.services.requests.post') as outbound:
            r = self.post(signature=signed)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(MessageLog.objects.filter(direction='in', content='hello').count(), 1)
        outbound.assert_not_called()  # a plain text with nothing waiting for it triggers no reply

    def test_unsigned_and_wrongly_signed_requests_are_refused_and_do_nothing(self):
        for signature in (None, 'sha256=' + '0' * 64, signed(b'{}'), lambda raw: signed(raw, 'a-different-secret'), 'garbage', ''):
            with patch('messaging.services.requests.post') as outbound:
                r = self.post(signature=signature)
            self.assertEqual(r.status_code, 403, signature)
            self.assert_nothing_happened(outbound)

    def test_the_signature_must_match_the_exact_body(self):
        raw = json.dumps(HOOK).encode()
        tampered = json.dumps({**HOOK, 'x': 1}).encode()
        with patch('messaging.services.requests.post') as outbound:
            r = self.client.post('/webhook', tampered, content_type='application/json', HTTP_X_HUB_SIGNATURE_256=signed(raw))
        self.assertEqual(r.status_code, 403)
        self.assert_nothing_happened(outbound)

    @override_settings(WHATSAPP_APP_SECRET='')
    def test_with_no_secret_configured_unsigned_requests_are_refused(self):
        with patch('messaging.services.requests.post') as outbound:
            r = self.post()
        self.assertEqual(r.status_code, 403)
        self.assert_nothing_happened(outbound)

    @override_settings(WHATSAPP_APP_SECRET='', WEBHOOK_ALLOW_UNSIGNED=True)
    def test_only_an_explicit_local_dev_opt_in_allows_unsigned_requests(self):
        self.assertEqual(self.post().status_code, 200)

    def test_meta_verification_handshake_still_works(self):
        ok = self.client.get('/webhook', {'hub.mode': 'subscribe', 'hub.verify_token': 'verify-me', 'hub.challenge': '777'})
        self.assertEqual((ok.status_code, ok.content), (200, b'777'))
        for params in ({'hub.mode': 'subscribe', 'hub.verify_token': 'wrong', 'hub.challenge': '1'},
                       {'hub.mode': 'subscribe', 'hub.challenge': '1'}, {}):
            self.assertEqual(self.client.get('/webhook', params).status_code, 403)

    def test_the_health_check_is_public_and_exposes_nothing_private(self):
        r = self.client.get('/api/health/')
        self.assertEqual(r.status_code, 200)
        text = r.content.decode().lower()
        for word in ('secret', 'token', 'password', 'key', 'version', 'path', '@'):
            self.assertNotIn(word, text)

    def test_the_only_public_api_routes_are_the_expected_ones(self):
        """If someone adds an open route later, this fails and forces a decision."""
        open_routes = set()
        for route, cls, _ in discover_routes():
            if cls is None or not route.startswith('api/'):
                continue
            if not any(issubclass(pc, IsSuperAdmin) for pc in getattr(cls, 'permission_classes', [])):
                open_routes.add(route)
        self.assertEqual(open_routes, set(PUBLIC_API) - {'api/health/'})  # health is a plain Django view
