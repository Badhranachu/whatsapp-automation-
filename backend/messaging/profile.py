"""The signed-in user's own profile: name, phone, photo, and password change by email code."""
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import audit
from .models import UserProfile
from .password_reset import RESEND_SECONDS, issue_otp, set_new_password, verify_code
from .serializers import IMAGE_SIGNATURES, SendMessageSerializer

MAX_NAME = 100
MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB


def _profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def _describe(user):
    p = _profile(user)
    return {
        'email': user.email,
        'name': user.first_name,
        'phone_number': p.phone_number,
        'is_superuser': user.is_superuser,
        'has_avatar': bool(p.avatar),
        'avatar_version': p.avatar_updated.isoformat() if p.avatar_updated else None,
    }


def _bad(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({'success': False, 'error': message}, status=code)


class ProfileView(APIView):
    def get(self, request):
        return Response(_describe(request.user))

    def patch(self, request):
        user, profile = request.user, _profile(request.user)
        before = {'name': user.first_name, 'phone_number': profile.phone_number}
        after = dict(before)
        if 'name' in request.data:
            name = ' '.join(str(request.data.get('name') or '').split())
            if len(name) > MAX_NAME:
                return _bad(f'Name must be {MAX_NAME} characters or fewer.')
            after['name'] = name
        if 'phone_number' in request.data:
            raw = str(request.data.get('phone_number') or '').strip()
            if raw:
                ser = SendMessageSerializer(data={'phone_number': raw})
                if not ser.is_valid():
                    return _bad('Enter a valid phone number, e.g. 9876543210 or +919876543210.')
                raw = ser.validated_data['phone_number']
            after['phone_number'] = raw
        user.first_name = after['name']
        user.save(update_fields=['first_name'])
        profile.phone_number = after['phone_number']
        profile.save(update_fields=['phone_number'])
        audit.record(request, 'update', 'profile', user.id, user.email, audit.diff(before, after))
        return Response({'success': True, 'profile': _describe(user)})


class AvatarView(APIView):
    """GET the picture, POST (multipart "image") to set it, DELETE to remove it."""

    parser_classes = [MultiPartParser, JSONParser]

    def get(self, request):
        p = _profile(request.user)
        if not p.avatar:
            return _bad('No profile picture.', status.HTTP_404_NOT_FOUND)
        resp = HttpResponse(bytes(p.avatar), content_type=p.avatar_type or 'image/png')
        resp['Cache-Control'] = 'private, max-age=0, must-revalidate'
        resp['X-Content-Type-Options'] = 'nosniff'
        return resp

    def post(self, request):
        f = request.FILES.get('image')
        if not f:
            return _bad('Choose a picture first.')
        if f.size > MAX_AVATAR_BYTES:
            return _bad('The picture must be 2 MB or smaller.')
        data = f.read()
        mime = next((m for sig, m in IMAGE_SIGNATURES.items() if data.startswith(sig)), None)
        if not mime:  # judged by the file's own bytes, not its name or declared type
            return _bad('Use a PNG or JPEG picture.')
        p = _profile(request.user)
        p.avatar, p.avatar_type, p.avatar_updated = data, mime, timezone.now()
        p.save(update_fields=['avatar', 'avatar_type', 'avatar_updated'])
        audit.record(request, 'update', 'profile', request.user.id, request.user.email, {'avatar': 'changed'})
        return Response({'success': True, 'profile': _describe(request.user)})

    def delete(self, request):
        p = _profile(request.user)
        p.avatar, p.avatar_type, p.avatar_updated = None, '', None
        p.save(update_fields=['avatar', 'avatar_type', 'avatar_updated'])
        audit.record(request, 'update', 'profile', request.user.id, request.user.email, {'avatar': 'removed'})
        return Response({'success': True, 'profile': _describe(request.user)})


class _Throttled(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'


class ProfilePasswordOtpView(_Throttled):
    """Email a code to the signed-in user's own address."""

    def post(self, request):
        user = request.user
        if not user.email:
            return _bad('Your account has no email address.')
        sent = issue_otp(request, user, user.email)
        audit.record(request, 'otp_requested', 'password', user.id, user.email, {'sent': sent})
        return Response({'success': True, 'sent': sent, 'resend_seconds': RESEND_SECONDS})


class ProfilePasswordVerifyView(_Throttled):
    def post(self, request):
        token = verify_code(request, request.user, request.data.get('otp'), request.user.email)
        if not token:
            return _bad('That code is wrong or has expired. Request a new one if needed.')
        return Response({'success': True, 'reset_token': token})


class ProfilePasswordChangeView(_Throttled):
    """Final step. The old login token is replaced, which signs out every device; the one that
    changed the password gets the new token back and stays signed in."""

    def post(self, request):
        error = set_new_password(
            request, request.user, request.data.get('reset_token'),
            str(request.data.get('password', '')), str(request.data.get('confirm_password', '')),
        )
        if error:
            return _bad(error)
        token = Token.objects.create(user=request.user)
        return Response({'success': True, 'message': 'Password changed.', 'token': token.key})
