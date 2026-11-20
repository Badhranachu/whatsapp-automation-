import re
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .login_otp import IST, mpin_enabled, mpin_matches, time_prefix
from .models import AuditLog, PasswordResetOtp

MPIN = '4829'


def at(hour, minute):
    return datetime(2026, 11, 21, hour, minute, 30, tzinfo=IST)


@override_settings(MPIN=MPIN)
class MpinRuleTests(SimpleTestCase):
    def test_time_is_typed_the_way_people_say_it(self):
        self.assertEqual(time_prefix(at(3, 30)), '330a')
        self.assertEqual(time_prefix(at(12, 5)), '1205p')
        self.assertEqual(time_prefix(at(0, 7)), '1207a')  # just after midnight is 12:07 am
        self.assertEqual(time_prefix(at(9, 7)), '907a')
        self.assertEqual(time_prefix(at(15, 45)), '345p')
        self.assertEqual(time_prefix(at(23, 59)), '1159p')

    def test_time_plus_mpin_plus_any_three_digits(self):
        now = at(3, 30)
        self.assertTrue(mpin_matches('330a' + MPIN + '123', now))
        self.assertTrue(mpin_matches('330a' + MPIN + '999', now))  # the 3 digits are not checked
        self.assertTrue(mpin_matches(' 330A ' + MPIN + ' 123 ', now))  # spaces and capitals are forgiven

    def test_one_minute_either_way_is_accepted_but_not_more(self):
        now = at(3, 30)
        self.assertTrue(mpin_matches('329a' + MPIN + '123', now))
        self.assertTrue(mpin_matches('331a' + MPIN + '123', now))
        self.assertFalse(mpin_matches('332a' + MPIN + '123', now))
        self.assertFalse(mpin_matches('328a' + MPIN + '123', now))

    def test_the_rest_must_be_exactly_right(self):
        now = at(3, 30)
        self.assertFalse(mpin_matches('330p' + MPIN + '123', now))  # pm instead of am
        self.assertFalse(mpin_matches('330a' + '4830' + '123', now))  # wrong MPIN
        self.assertFalse(mpin_matches('330a' + MPIN, now))  # the 3 extra digits are missing
        self.assertFalse(mpin_matches('330a' + MPIN + '1234', now))  # too many extra digits
        self.assertFalse(mpin_matches('330a' + MPIN + '12a', now))  # extra characters must be digits
        self.assertFalse(mpin_matches('', now))
        self.assertFalse(mpin_matches(None, now))
        self.assertFalse(mpin_matches(MPIN + '123', now))  # no time at all

    def test_midnight_and_noon_edges(self):
        self.assertTrue(mpin_matches('1200a' + MPIN + '111', at(0, 0)))
        self.assertTrue(mpin_matches('1200p' + MPIN + '111', at(12, 0)))
        self.assertTrue(mpin_matches('1159p' + MPIN + '111', at(0, 0) - timedelta(minutes=1)))

    def test_only_a_valid_mpin_turns_it_on(self):
        for value, expected in (('4829', True), ('0000', True), ('482', False), ('48291', False), ('482915', False),
                                ('abcd', False), ('48 9', False), ('', False)):
            with override_settings(MPIN=value):
                self.assertEqual(mpin_enabled(), expected, value)


@override_settings(LOGIN_OTP_REQUIRED=True, MPIN=MPIN, OTP_EMAIL_ASYNC=False)
class MpinOnlyLoginTests(APITestCase):
    """With an MPIN set: password, then the MPIN entry (time + MPIN + 3 digits). No email code is ever sent."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_superuser('boss@example.com', 'boss@example.com', 'secret-pass-1')

    def step1(self):
        return self.client.post('/api/auth/login/', {'email': 'boss@example.com', 'password': 'secret-pass-1'}, format='json')

    def box(self, challenge, typed):
        return self.client.post('/api/auth/login/verify/', {'challenge': challenge, 'otp': typed}, format='json')

    def good(self):
        return time_prefix(datetime.now(IST)) + MPIN + '123'

    def bad(self):
        return time_prefix(datetime.now(IST)) + '0000' + '123'

    def test_nothing_is_emailed_and_no_token_yet(self):
        body = self.step1().json()
        self.assertEqual(body['methods'], ['mpin'])
        self.assertFalse(body['code_sent'])
        self.assertNotIn('token', body)
        self.assertEqual(body['email_hint'], 'bo**@example.com')  # lets the screen look like a code screen
        self.assertEqual((len(mail.outbox), PasswordResetOtp.objects.count()), (0, 0))

    def test_time_plus_mpin_plus_three_digits_signs_in(self):
        challenge = self.step1().json()['challenge']
        r = self.box(challenge, self.good())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['token'] and r.json()['is_superuser'])
        self.assertEqual(AuditLog.objects.get(action='login').changes, {'method': 'mpin'})
        self.assertEqual(len(mail.outbox), 0)

    def test_wrong_mpin_is_refused_and_never_stored(self):
        challenge = self.step1().json()['challenge']
        typed = self.bad()
        r = self.box(challenge, typed)
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('token', r.json())
        self.assertEqual(AuditLog.objects.filter(action='mpin_failed').count(), 1)
        dump = str(list(AuditLog.objects.values()))
        self.assertNotIn(typed, dump)
        self.assertNotIn(MPIN, dump)

    def test_a_plain_six_digit_number_is_not_an_email_code_here(self):
        challenge = self.step1().json()['challenge']
        self.assertEqual(self.box(challenge, '123456').status_code, 400)
        self.assertEqual(Token_count(), 0)

    def test_five_wrong_tries_block_it_for_fifteen_minutes(self):
        challenge = self.step1().json()['challenge']
        for _ in range(5):
            self.assertEqual(self.box(challenge, self.bad()).status_code, 400)
        blocked = self.box(challenge, self.good())  # even the right MPIN is refused now
        self.assertEqual(blocked.status_code, 429)
        self.assertNotIn('token', blocked.json())
        AuditLog.objects.filter(action='mpin_failed').update(created_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self.box(challenge, self.good()).status_code, 200)

    def test_a_good_sign_in_resets_the_count(self):
        challenge = self.step1().json()['challenge']
        for _ in range(4):
            self.box(challenge, self.bad())
        self.assertEqual(self.box(challenge, self.good()).status_code, 200)
        for _ in range(4):  # four more wrong tries are fine because the counter restarted at the sign-in
            self.assertEqual(self.box(challenge, self.bad()).status_code, 400)
        self.assertEqual(self.box(challenge, self.good()).status_code, 200)

    def test_needs_the_password_step_first(self):
        self.assertEqual(self.box('forged', self.good()).status_code, 400)
        self.assertEqual(self.box('', self.good()).status_code, 400)

    def test_asking_for_an_email_code_is_refused_in_this_mode(self):
        challenge = self.step1().json()['challenge']
        r = self.client.post('/api/auth/login/resend/', {'challenge': challenge}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_blank_or_short_entries_do_not_use_up_the_tries(self):
        challenge = self.step1().json()['challenge']
        for typed in ('', 'abc', '12345', ' ', '330a'):
            self.assertEqual(self.box(challenge, typed).status_code, 400, repr(typed))
        self.assertEqual(AuditLog.objects.filter(action='mpin_failed').count(), 0)

    def test_failure_messages_never_explain_or_mention_the_mpin(self):
        challenge = self.step1().json()['challenge']
        messages = [self.box(challenge, self.bad()).json()['error'], self.box(challenge, '').json()['error']]
        for _ in range(5):
            self.box(challenge, self.bad())
        messages.append(self.box(challenge, self.good()).json()['error'])  # blocked
        messages.append(self.client.post('/api/auth/login/resend/', {'challenge': challenge}, format='json').json()['error'])
        for text in messages:
            for word in ('mpin', 'india', 'time', 'digit', '330a', 'pin'):
                self.assertNotIn(word, text.lower(), text)

    def test_time_comes_from_india_not_the_server_clock(self):
        challenge = self.step1().json()['challenge']
        india_morning = datetime(2026, 11, 21, 3, 30, 10, tzinfo=IST)
        with patch('messaging.login_otp._now_ist', return_value=india_morning):
            self.assertEqual(self.box(challenge, '330a' + MPIN + '123').status_code, 200)


@override_settings(LOGIN_OTP_REQUIRED=True, OTP_EMAIL_ASYNC=False)
class WithoutMpinTests(APITestCase):
    """No (or an invalid) MPIN: the emailed 6-digit code is used instead."""

    def setUp(self):
        cache.clear()
        User.objects.create_superuser('boss@example.com', 'boss@example.com', 'secret-pass-1')

    def test_empty_or_too_short_mpin_falls_back_to_the_emailed_code(self):
        for value in ('', '123', '12345', '482915'):
            with override_settings(MPIN=value):
                mail.outbox.clear()
                body = self.client.post('/api/auth/login/', {'email': 'boss@example.com', 'password': 'secret-pass-1'}, format='json').json()
                self.assertEqual(body['methods'], ['email'], value)
                self.assertTrue(body['code_sent'])
                self.assertEqual(len(mail.outbox), 1)
                code = re.search(r'code is (\d{6})', mail.outbox[0].body).group(1)
                r = self.client.post('/api/auth/login/verify/', {'challenge': body['challenge'], 'otp': code}, format='json')
                self.assertEqual(r.status_code, 200, value)
                PasswordResetOtp.objects.all().delete()
                cache.clear()


def Token_count():
    from rest_framework.authtoken.models import Token
    return Token.objects.count()
