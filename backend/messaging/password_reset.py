"""Forgot password for admins: email -> OTP -> new password.

Security notes
- The reply to "send me a code" is identical for every email, so nobody can learn which
  emails are admin accounts. A code is only ever emailed to an active super admin.
- Codes are 6 digits, valid 10 minutes, single use, and stored as a keyed hash.
- 5 wrong guesses burn the code; a new code can be requested once a minute.
- After the code is verified the client gets a random reset token that the last step needs.
- Resetting the password signs the account out everywhere (all API tokens are deleted).
"""
import hashlib
import hmac
import logging
import secrets
import threading
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import audit
from .models import PasswordResetOtp

logger = logging.getLogger(__name__)

OTP_MINUTES = 10
RESEND_SECONDS = 60
MAX_ATTEMPTS = 5

SENT_MESSAGE = 'If this email belongs to an admin account, a 6-digit code has been sent to it.'
BAD_CODE = 'That code is wrong or has expired. Request a new one if needed.'
BAD_SESSION = 'This reset has expired. Please start again.'


class OtpDeliveryError(Exception):
    """The email with the code could not be sent."""


def _hash(value, user_id, purpose='reset'):
    """Keyed hash (SECRET_KEY) so a leaked database row cannot be used to guess codes offline.

    A code is only valid for the purpose it was issued for: a password-reset code can never complete a sign-in.
    """
    msg = (f'{user_id}:{value}' if purpose == 'reset' else f'{user_id}:{purpose}:{value}').encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def _find_admin(email):
    email = str(email or '').strip()
    if not email:
        return None
    return User.objects.filter(email__iexact=email, is_superuser=True, is_active=True).first()


def _email_otp(address, code, purpose='reset'):
    """Send the code. Returns True when the mail server accepted it."""
    if purpose == 'login':
        subject = 'Your WhatsApp Messenger sign-in code'
        tail = 'If you did not just try to sign in, someone may know your password: please change it.'
    else:
        subject = 'Your WhatsApp Messenger password reset code'
        tail = 'If you did not ask for it, ignore this email: your password has not changed.'
    try:
        send_mail(
            subject,
            f'Your code is {code}.\n\nIt works for {OTP_MINUTES} minutes and can be used once. {tail}',
            settings.DEFAULT_FROM_EMAIL,
            [address],
            fail_silently=False,
        )
        return True
    except Exception:  # noqa: BLE001  never reveal mail problems to the caller
        logger.exception('Could not send the %s code email', purpose)
        return False


def _deliver(address, code, purpose='reset', sync=False):
    if sync:
        return _email_otp(address, code, purpose)
    if getattr(settings, 'OTP_EMAIL_ASYNC', False):
        threading.Thread(target=_email_otp, args=(address, code, purpose), daemon=True).start()
    else:
        _email_otp(address, code, purpose)
    return True


def issue_otp(request, user, label='', purpose='reset', sync=False):
    """Email a fresh code to `user` (at most one a minute). Returns True when one was sent.

    With sync=True the email is sent before returning, and OtpDeliveryError is raised (and the code
    discarded) when it cannot be sent, so the caller can tell the person instead of leaving them waiting.
    """
    latest = PasswordResetOtp.objects.filter(user=user).first()
    if latest and latest.created_at > timezone.now() - timedelta(seconds=RESEND_SECONDS):
        return False
    code = f'{secrets.randbelow(10**6):06d}'
    with transaction.atomic():
        PasswordResetOtp.objects.filter(user=user, used=False).update(used=True)
        otp = PasswordResetOtp.objects.create(
            user=user,
            code_hash=_hash(code, user.id, purpose),
            expires_at=timezone.now() + timedelta(minutes=OTP_MINUTES),
        )
    if not _deliver(user.email, code, purpose, sync):
        otp.delete()  # nothing was sent, so do not block an immediate retry
        raise OtpDeliveryError('The code could not be emailed.')
    return True


def verify_code(request, user, code, label=''):
    """Check the emailed code. Returns a reset token on success, None otherwise (counts the try)."""
    code = str(code or '').strip()
    otp = (
        PasswordResetOtp.objects.filter(user=user, used=False, expires_at__gt=timezone.now()).first()
        if user
        else None
    )
    if not otp or otp.attempts >= MAX_ATTEMPTS:
        audit.record(request, 'otp_failed', 'password', '', label, {'reason': 'no_active_code'})
        return None
    # Count the attempt before comparing so parallel guesses cannot beat the limit.
    PasswordResetOtp.objects.filter(pk=otp.pk).update(attempts=otp.attempts + 1)
    if not (code.isdigit() and len(code) == 6 and hmac.compare_digest(_hash(code, user.id), otp.code_hash)):
        audit.record(request, 'otp_failed', 'password', '', label, {'reason': 'wrong_code'})
        return None
    token = secrets.token_urlsafe(32)
    otp.token_hash = _hash(token, user.id)
    otp.expires_at = timezone.now() + timedelta(minutes=OTP_MINUTES)  # time to type the password
    otp.save(update_fields=['token_hash', 'expires_at'])
    audit.record(request, 'otp_verified', 'password', user.id, label)
    return token


def set_new_password(request, user, token, password, confirm, keep_token=None):
    """Last step. Returns an error message, or None when the password was changed.

    Signs the account out everywhere, except `keep_token` (the session that is changing it).
    """
    token = str(token or '')
    otp = (
        PasswordResetOtp.objects.filter(user=user, used=False, expires_at__gt=timezone.now())
        .exclude(token_hash='')
        .first()
        if user
        else None
    )
    if not otp or not token or not hmac.compare_digest(_hash(token, user.id), otp.token_hash):
        return BAD_SESSION
    if password != confirm:
        return 'Passwords do not match.'
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        return ' '.join(exc.messages)
    with transaction.atomic():
        user.set_password(password)
        user.save(update_fields=['password'])
        others = Token.objects.filter(user=user)
        if keep_token is not None:
            others = others.exclude(key=getattr(keep_token, 'key', keep_token))
        others.delete()
        PasswordResetOtp.objects.filter(user=user).update(used=True)
    audit.record(request, 'password_reset', 'user', user.id, user.email, user=user)
    return None


class _ResetView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'


class ForgotPasswordView(_ResetView):
    """Step 1. Body: {"email"}. Always answers the same, whoever the email belongs to."""

    def post(self, request):
        email = str(request.data.get('email', '')).strip()[:150]
        user = _find_admin(email)
        sent = issue_otp(request, user, email) if user else False
        audit.record(request, 'otp_requested', 'password', user.id if user else '', email, {'sent': sent})
        return Response({'success': True, 'message': SENT_MESSAGE, 'resend_seconds': RESEND_SECONDS})


class VerifyOtpView(_ResetView):
    """Step 2. Body: {"email", "otp"}. Returns a one-time reset token when the code is right."""

    def post(self, request):
        email = str(request.data.get('email', '')).strip()
        token = verify_code(request, _find_admin(email), request.data.get('otp'), email)
        if not token:
            return Response({'success': False, 'error': BAD_CODE}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'success': True, 'reset_token': token})


class ResetPasswordView(_ResetView):
    """Step 3. Body: {"email", "reset_token", "password", "confirm_password"}."""

    def post(self, request):
        user = _find_admin(str(request.data.get('email', '')).strip())
        error = set_new_password(
            request, user, request.data.get('reset_token'),
            str(request.data.get('password', '')), str(request.data.get('confirm_password', '')),
        )
        if error:
            return Response({'success': False, 'error': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'success': True, 'message': 'Password updated. Please sign in.'})
