import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import AuditLog, PasswordResetOtp

NEW_PASSWORD = 'Brand-new-pass-77'


@override_settings(OTP_EMAIL_ASYNC=False)
class PasswordResetTests(APITestCase):
    def setUp(self):
        cache.clear()  # throttle counters
        self.admin = User.objects.create_superuser('boss@example.com', 'boss@example.com', 'old-pass-12345')
        self.plain = User.objects.create_user('staff@example.com', 'staff@example.com', 'staff-pass-12345')

    def forgot(self, email):
        return self.client.post('/api/auth/forgot-password/', {'email': email}, format='json')

    def code_from_mail(self):
        return re.search(r'code is (\d{6})', mail.outbox[-1].body).group(1)

    def verify(self, email, code):
        return self.client.post('/api/auth/verify-otp/', {'email': email, 'otp': code}, format='json')

    def reset(self, email, token, password=NEW_PASSWORD, confirm=None):
        return self.client.post('/api/auth/reset-password/', {
            'email': email, 'reset_token': token, 'password': password,
            'confirm_password': password if confirm is None else confirm,
        }, format='json')

    def test_full_flow_changes_password_and_signs_out_everywhere(self):
        Token.objects.create(user=self.admin)
        self.assertEqual(self.forgot('BOSS@example.com').status_code, 200)  # case-insensitive
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['boss@example.com'])
        token = self.verify('boss@example.com', self.code_from_mail()).json()['reset_token']
        self.assertEqual(self.reset('boss@example.com', token).status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password(NEW_PASSWORD))
        self.assertFalse(Token.objects.filter(user=self.admin).exists())
        login = self.client.post('/api/auth/login/', {'email': 'boss@example.com', 'password': NEW_PASSWORD}, format='json')
        self.assertEqual(login.status_code, 200)
        # the token and code cannot be reused
        self.assertEqual(self.reset('boss@example.com', token).status_code, 400)

    def test_reply_is_identical_for_admin_unknown_and_non_admin_and_only_admin_gets_mail(self):
        replies = [self.forgot(e).json() for e in ('boss@example.com', 'nobody@example.com', 'staff@example.com', '')]
        self.assertEqual(len({str(r) for r in replies}), 1)
        self.assertEqual([m.to for m in mail.outbox], [['boss@example.com']])
        self.assertEqual(PasswordResetOtp.objects.count(), 1)

    def test_wrong_code_then_limit_burns_the_code(self):
        self.forgot('boss@example.com')
        code = self.code_from_mail()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            self.assertEqual(self.verify('boss@example.com', wrong).status_code, 400)
        self.assertEqual(self.verify('boss@example.com', code).status_code, 400)  # right code, but burnt

    def test_expired_code_rejected(self):
        self.forgot('boss@example.com')
        PasswordResetOtp.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify('boss@example.com', self.code_from_mail()).status_code, 400)

    def test_non_admin_cannot_verify_or_reset(self):
        self.forgot('staff@example.com')
        self.assertEqual(self.verify('staff@example.com', '123456').status_code, 400)
        self.assertEqual(self.reset('staff@example.com', 'x' * 40).status_code, 400)

    def test_resend_is_rate_limited_and_new_code_replaces_old(self):
        self.forgot('boss@example.com')
        self.forgot('boss@example.com')  # within a minute: silently ignored
        self.assertEqual(len(mail.outbox), 1)
        first = self.code_from_mail()
        PasswordResetOtp.objects.update(created_at=timezone.now() - timedelta(minutes=2))
        self.forgot('boss@example.com')
        self.assertEqual(len(mail.outbox), 2)
        if first != self.code_from_mail():
            self.assertEqual(self.verify('boss@example.com', first).status_code, 400)

    def test_reset_needs_the_token_and_a_good_matching_password(self):
        self.forgot('boss@example.com')
        token = self.verify('boss@example.com', self.code_from_mail()).json()['reset_token']
        self.assertEqual(self.reset('boss@example.com', 'wrong-token').status_code, 400)
        self.assertEqual(self.reset('boss@example.com', token, confirm='different').status_code, 400)
        self.assertEqual(self.reset('boss@example.com', token, password='123').status_code, 400)  # too weak
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('old-pass-12345'))
        self.assertEqual(self.reset('boss@example.com', token).status_code, 200)  # still valid after typos

    def test_reset_without_verifying_the_code_is_refused(self):
        self.forgot('boss@example.com')
        self.assertEqual(self.reset('boss@example.com', '').status_code, 400)

    def test_audit_trail_has_no_secrets(self):
        self.forgot('boss@example.com')
        code = self.code_from_mail()
        token = self.verify('boss@example.com', code).json()['reset_token']
        self.reset('boss@example.com', token)
        actions = set(AuditLog.objects.values_list('action', flat=True))
        self.assertTrue({'otp_requested', 'otp_verified', 'password_reset'} <= actions)
        dump = str(list(AuditLog.objects.values()))
        for secret in (code, token, NEW_PASSWORD):
            self.assertNotIn(secret, dump)
