"""Sign-in with an emailed 6-digit code, after the password has been accepted.

Step 1  POST /api/auth/login/          email + password  ->  no token yet. A short-lived signed "challenge" is returned.
Step 2  POST /api/auth/login/verify/   challenge + one typed value  ->  the API token.

Which second step is used depends on whether an MPIN is set in .env:
- MPIN set   -> NO email is sent. The value typed is the MPIN entry: Indian time (12-hour HHMM + a/p, e.g. 330a for
                3:30 am) + the MPIN + any 3 digits, e.g. 330a482915123. The 3 trailing digits are only padding and are
                not checked. The time may be one minute off either way. One shared MPIN (exactly 4 digits). After 5 wrong
                tries the MPIN is blocked for 15 minutes for that account. The tries are counted in the audit log per
                account, so the limit cannot be dodged by changing IP address.
- MPIN empty -> a 6-digit code is emailed (POST /api/auth/login/resend/ sends a fresh one) and that code is typed.

Notes
- The challenge only proves that the password was right a moment ago (signed, 10 minutes). It is not a login.
- A code works once, for 10 minutes, and is burnt after 5 wrong tries. It is stored as a keyed hash and is only
  valid for signing in (a password-reset code cannot be used here).
- Mail that cannot be sent is reported to the person, so they are never left waiting for a code that is not coming.
"""
import hmac
import re
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing
from django.utils import timezone as dj_timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import audit
from .models import AuditLog, PasswordResetOtp
from .password_reset import (
    MAX_ATTEMPTS,
    RESEND_SECONDS,
    OtpDeliveryError,
    _hash,
    issue_otp,
)

PURPOSE = 'login'
CHALLENGE_SALT = 'whatsapp-login-challenge'
CHALLENGE_MINUTES = 10
BAD_CODE = 'That code is wrong or has expired. Request a new one if needed.'
EXPIRED = 'Your sign-in expired. Please enter your email and password again.'
BAD_MPIN = 'That code is not correct.'
MPIN_LOCKED = 'Too many wrong attempts. Please try again in 15 minutes.'
MPIN_OFF = 'MPIN sign-in is not turned on.'
MPIN_MAX_TRIES = 5
MPIN_LOCK_MINUTES = 15
MPIN_EXTRA_DIGITS = 3
IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving, so a fixed offset is exact
MAIL_FAILED = 'We could not email the sign-in code. Please try again in a moment.'


def _mask(email):
    local, _, domain = str(email).partition('@')
    return f'{local[:2]}{"*" * max(1, len(local) - 2)}@{domain}'


def mpin_enabled():
    """MPIN sign-in is on only when the MPIN setting is exactly 4 digits."""
    return bool(re.fullmatch(r'\d{4}', settings.MPIN or ''))


def _now_ist():
    return datetime.now(IST)


def time_prefix(moment):
    """12-hour time as typed: 3:30 am -> '330a', 12:05 pm -> '1205p', 9:07 am -> '907a'."""
    return f'{moment.hour % 12 or 12}{moment.minute:02d}{"a" if moment.hour < 12 else "p"}'


def mpin_matches(typed, now=None):
    """True when `typed` is the Indian time (this minute, +-1) + the MPIN + any 3 digits."""
    mpin = settings.MPIN
    typed = ''.join(str(typed or '').split()).lower()
    now = now or _now_ist()
    ok = False
    for delta in (0, -1, 1):  # check all three so the timing does not depend on which one matches
        prefix = time_prefix(now + timedelta(minutes=delta))
        rest = typed[len(prefix):] if typed.startswith(prefix) else None
        if rest is not None and rest.isdigit() and len(rest) == len(mpin) + MPIN_EXTRA_DIGITS:
            ok = hmac.compare_digest(rest[:len(mpin)], mpin) or ok
    return ok


def _mpin_locked(user):
    """Five wrong MPINs in the last 15 minutes (since the last successful sign-in) block the MPIN."""
    since = dj_timezone.now() - timedelta(minutes=MPIN_LOCK_MINUTES)
    last_ok = AuditLog.objects.filter(actor=user, action='login').first()
    if last_ok and last_ok.created_at > since:
        since = last_ok.created_at
    return AuditLog.objects.filter(actor=user, action='mpin_failed', created_at__gte=since).count() >= MPIN_MAX_TRIES


def finish_login(request, user, method='password'):
    """Issue the API token (the end of a successful sign-in)."""
    token, _ = Token.objects.get_or_create(user=user)
    audit.record(request, 'login', 'session', user.id, user.email, {'method': method}, user=user)
    return Response({
        'success': True, 'token': token.key, 'email': user.email, 'is_superuser': user.is_superuser,
    })


def start_login_challenge(request, user):
    """The password was right: hand back a challenge instead of a token.

    With an MPIN configured nothing is emailed (the person types the MPIN entry); otherwise a code is emailed.
    """
    challenge = signing.dumps({'uid': user.id}, salt=CHALLENGE_SALT)
    if mpin_enabled():
        audit.record(request, 'login_password_ok', 'session', user.id, user.email, user=user)
        # Nothing is emailed. The address is returned only so the screen can look like an ordinary code screen.
        return Response({
            'success': True, 'otp_required': True, 'challenge': challenge, 'methods': ['mpin'], 'code_sent': False,
            'email_hint': _mask(user.email), 'resend_seconds': RESEND_SECONDS,
        })
    try:
        issue_otp(request, user, user.email, purpose=PURPOSE, sync=True)
    except OtpDeliveryError:
        audit.record(request, 'login_code_failed', 'session', user.id, user.email, {'reason': 'email_not_sent'}, user=user)
        return Response({'success': False, 'error': MAIL_FAILED}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    audit.record(request, 'login_code_sent', 'session', user.id, user.email, user=user)
    return Response({
        'success': True,
        'otp_required': True,
        'challenge': challenge,
        'methods': ['email'],
        'code_sent': True,
        'email_hint': _mask(user.email),
        'resend_seconds': RESEND_SECONDS,
    })


def _user_from_challenge(raw):
    try:
        data = signing.loads(str(raw or ''), salt=CHALLENGE_SALT, max_age=CHALLENGE_MINUTES * 60)
    except signing.BadSignature:
        return None
    return User.objects.filter(pk=data.get('uid'), is_active=True, is_superuser=True).first()


class _LoginStepView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login_otp'


class LoginVerifyView(_LoginStepView):
    """Body: {"challenge", "otp"}: the MPIN entry (time + MPIN + 3 digits) when an MPIN is set, else the emailed code."""

    def post(self, request):
        user = _user_from_challenge(request.data.get('challenge'))
        if not user:
            return Response({'success': False, 'error': EXPIRED}, status=status.HTTP_400_BAD_REQUEST)
        typed = ''.join(str(request.data.get('otp', '')).split()).lower()
        if len(typed) < 6:  # blank or far too short: just refuse, it is not a real attempt
            return Response({'success': False, 'error': BAD_MPIN if mpin_enabled() else BAD_CODE}, status=status.HTTP_400_BAD_REQUEST)
        if mpin_enabled():
            return self._check_mpin(request, user, typed)  # no email code exists in this mode
        if re.fullmatch(r'\d{6}', typed):
            return self._check_email_code(request, user, typed)
        return Response({'success': False, 'error': BAD_CODE}, status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    def _check_email_code(request, user, code):
        otp = PasswordResetOtp.objects.filter(user=user, used=False, expires_at__gt=dj_timezone.now()).first()
        if not otp or otp.attempts >= MAX_ATTEMPTS:
            audit.record(request, 'login_code_failed', 'session', user.id, user.email, {'reason': 'no_active_code'}, user=user)
            return Response({'success': False, 'error': BAD_CODE}, status=status.HTTP_400_BAD_REQUEST)
        # Count the attempt before comparing so parallel guesses cannot beat the limit.
        PasswordResetOtp.objects.filter(pk=otp.pk).update(attempts=otp.attempts + 1)
        if not hmac.compare_digest(_hash(code, user.id, PURPOSE), otp.code_hash):
            audit.record(request, 'login_code_failed', 'session', user.id, user.email, {'reason': 'wrong_code'}, user=user)
            return Response({'success': False, 'error': BAD_CODE}, status=status.HTTP_400_BAD_REQUEST)
        PasswordResetOtp.objects.filter(user=user).update(used=True)  # single use
        return finish_login(request, user, 'email')

    @staticmethod
    def _check_mpin(request, user, typed):
        if _mpin_locked(user):
            audit.record(request, 'mpin_blocked', 'session', user.id, user.email, user=user)
            return Response({'success': False, 'error': MPIN_LOCKED}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if not mpin_matches(typed):
            audit.record(request, 'mpin_failed', 'session', user.id, user.email, user=user)  # never stores what was typed
            return Response({'success': False, 'error': BAD_MPIN}, status=status.HTTP_400_BAD_REQUEST)
        PasswordResetOtp.objects.filter(user=user).update(used=True)  # the emailed code is no longer needed
        return finish_login(request, user, 'mpin')


class LoginResendView(_LoginStepView):
    """Body: {"challenge"}. Emails a new code (at most one a minute)."""

    def post(self, request):
        user = _user_from_challenge(request.data.get('challenge'))
        if not user:
            return Response({'success': False, 'error': EXPIRED}, status=status.HTTP_400_BAD_REQUEST)
        if mpin_enabled():
            return Response({'success': False, 'error': 'Please wait a minute before asking for another code.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            sent = issue_otp(request, user, user.email, purpose=PURPOSE, sync=True)
        except OtpDeliveryError:
            return Response({'success': False, 'error': MAIL_FAILED}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if sent:
            audit.record(request, 'login_code_sent', 'session', user.id, user.email, {'resend': True}, user=user)
        return Response({'success': True, 'sent': sent, 'resend_seconds': RESEND_SECONDS})
