import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from .models import AuditLog, PasswordResetOtp
from .password_reset import issue_otp


@override_settings(LOGIN_OTP_REQUIRED=True, MPIN='')
class LoginOtpTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_superuser('boss@example.com', 'boss@example.com', 'secret-pass-1')

    def step1(self, password='secret-pass-1', email='boss@example.com'):
        return self.client.post('/api/auth/login/', {'email': email, 'password': password}, format='json')

    def code(self):
        return re.search(r'code is (\d{6})', mail.outbox[-1].body).group(1)

    def verify(self, challenge, code):
        return self.client.post('/api/auth/login/verify/', {'challenge': challenge, 'otp': code}, format='json')

    def test_password_alone_gives_no_token_and_emails_a_code(self):
        r = self.step1()
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['otp_required'])
        self.assertNotIn('token', body)
        self.assertEqual(body['email_hint'], 'bo**@example.com')
        self.assertEqual(Token.objects.count(), 0)
        self.assertEqual((len(mail.outbox), mail.outbox[0].to), (1, ['boss@example.com']))
        self.assertIn('sign-in code', mail.outbox[0].subject)

    def test_correct_code_signs_in_and_works_once(self):
        challenge = self.step1().json()['challenge']
        code = self.code()
        r = self.verify(challenge, code)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['token'] and r.json()['is_superuser'])
        authed = APIClient()
        authed.credentials(HTTP_AUTHORIZATION=f'Token {r.json()["token"]}')
        self.assertEqual(authed.get('/api/auth/me/').status_code, 200)
        self.assertEqual(self.verify(challenge, code).status_code, 400)  # the code is burnt
        self.assertTrue({'login_code_sent', 'login'} <= set(AuditLog.objects.values_list('action', flat=True)))

    def test_wrong_password_sends_nothing(self):
        self.assertEqual(self.step1('nope').status_code, 401)
        self.assertEqual((len(mail.outbox), PasswordResetOtp.objects.count()), (0, 0))

    def test_wrong_code_is_refused_and_five_tries_burn_it(self):
        challenge = self.step1().json()['challenge']
        code = self.code()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            self.assertEqual(self.verify(challenge, wrong).status_code, 400)
        self.assertEqual(self.verify(challenge, code).status_code, 400)  # right code, but burnt
        self.assertEqual(Token.objects.count(), 0)

    def test_challenge_must_be_genuine_and_fresh(self):
        self.step1()
        code = self.code()
        self.assertEqual(self.verify('forged-challenge', code).status_code, 400)
        self.assertEqual(self.verify('', code).status_code, 400)
        challenge = self.step1().json()['challenge']
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 11 * 60):
            self.assertEqual(self.verify(challenge, self.code()).status_code, 400)  # challenge expired

    def test_expired_code_is_refused(self):
        challenge = self.step1().json()['challenge']
        PasswordResetOtp.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify(challenge, self.code()).status_code, 400)

    def test_resend_waits_a_minute_then_replaces_the_old_code(self):
        challenge = self.step1().json()['challenge']
        first = self.code()
        r = self.client.post('/api/auth/login/resend/', {'challenge': challenge}, format='json')
        self.assertEqual((r.status_code, r.json()['sent']), (200, False))  # too soon
        self.assertEqual(len(mail.outbox), 1)
        PasswordResetOtp.objects.update(created_at=timezone.now() - timedelta(minutes=2))
        r = self.client.post('/api/auth/login/resend/', {'challenge': challenge}, format='json')
        self.assertTrue(r.json()['sent'])
        self.assertEqual(len(mail.outbox), 2)
        second = self.code()
        if first != second:
            self.assertEqual(self.verify(challenge, first).status_code, 400)
        self.assertEqual(self.verify(challenge, second).status_code, 200)

    def test_a_password_reset_code_cannot_complete_a_sign_in(self):
        challenge = self.step1().json()['challenge']
        PasswordResetOtp.objects.all().delete()
        with override_settings(OTP_EMAIL_ASYNC=False):
            issue_otp(None, self.user, self.user.email, purpose='reset')
        self.assertEqual(self.verify(challenge, self.code()).status_code, 400)
        self.assertEqual(Token.objects.count(), 0)

    def test_mail_failure_is_reported_and_does_not_block_a_retry(self):
        with patch('messaging.password_reset.send_mail', side_effect=OSError('smtp down')):
            r = self.step1()
        self.assertEqual(r.status_code, 503)
        self.assertNotIn('token', r.json())
        self.assertEqual(PasswordResetOtp.objects.count(), 0)
        self.assertEqual(self.step1().status_code, 200)  # retry straight away works

    def test_switched_off_gives_the_token_directly(self):
        with override_settings(LOGIN_OTP_REQUIRED=False):
            r = self.step1()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['token'])
        self.assertEqual(len(mail.outbox), 0)

    def test_audit_log_never_stores_codes(self):
        challenge = self.step1().json()['challenge']
        code = self.code()
        self.verify(challenge, code)
        self.assertNotIn(code, str(list(AuditLog.objects.values())))
        self.assertNotIn(challenge, str(list(AuditLog.objects.values())))
