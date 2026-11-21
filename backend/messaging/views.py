from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework import generics
from rest_framework.authtoken.models import Token
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import audit
from .login_otp import finish_login, start_login_challenge
from .models import MessageLog, MessageTemplate, log_message
from .serializers import MessageTemplateSerializer, SendMessageSerializer
from .services import (
    ConfigurationError,
    WhatsAppError,
    send_template_message,
    send_uploaded_image,
)

FAIL = 'Unable to send WhatsApp message.'
HISTORY_LIMIT = 100


class LoginView(APIView):
    """Email + password login; returns an API token."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        email = str(request.data.get('email', '')).strip()
        password = str(request.data.get('password', ''))
        user = None
        if email and password:
            candidate = User.objects.filter(email__iexact=email).first()
            if candidate:
                user = authenticate(request, username=candidate.get_username(), password=password)
        # Only active super admins can sign in. Everyone else gets the same answer as a wrong password.
        if not user or not user.is_active or not user.is_superuser:
            audit.record(request, 'login_failed', 'session', label=email[:150])
            return Response(
                {'success': False, 'error': 'Invalid email or password.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if settings.LOGIN_OTP_REQUIRED:
            return start_login_challenge(request, user)
        return finish_login(request, user)


class LogoutView(APIView):
    def post(self, request):
        audit.record(request, 'logout', 'session', request.user.id, request.user.email)
        Token.objects.filter(user=request.user).delete()
        return Response({'success': True})


class MeView(APIView):
    def get(self, request):
        return Response({'email': request.user.email, 'is_superuser': request.user.is_superuser})


class StatsView(APIView):
    """Summary counts for the dashboard."""

    def get(self, request):
        out = MessageLog.objects.filter(direction=MessageLog.OUT)
        return Response({
            'sent_total': out.count(),
            'delivered': out.filter(status__in=['delivered', 'read']).count(),
            'failed': out.filter(status='failed').count(),
            'received': MessageLog.objects.filter(direction=MessageLog.IN).count(),
        })


class MessageHistoryView(APIView):
    """Recent sent/received messages, newest first. Optional ?direction=in|out&q=phone."""

    def get(self, request):
        rows = MessageLog.objects.select_related('template', 'flow_run')
        template_id = request.query_params.get('template')
        if template_id and template_id.isdigit():
            rows = rows.filter(template_id=int(template_id))
        direction = request.query_params.get('direction')
        if direction in (MessageLog.IN, MessageLog.OUT):
            rows = rows.filter(direction=direction)
        q = request.query_params.get('q', '').strip()
        if q:
            rows = rows.filter(phone_number__contains=q.lstrip('+').replace(' ', ''))
        try:
            limit = min(int(request.query_params.get('limit', HISTORY_LIMIT)), 500)
        except ValueError:
            limit = HISTORY_LIMIT
        rows = rows[:limit]
        return Response([
            {
                'id': m.id,
                'direction': m.direction,
                'phone_number': m.phone_number,
                'message_type': m.message_type,
                'content': m.content,
                'wa_message_id': m.wa_message_id,
                'status': m.status,
                'status_detail': m.status_detail,
                'template': (
                    {'id': m.template_id, 'name': m.template.name}
                    if m.template_id
                    else ({'id': None, 'name': m.flow_run.template_name} if m.flow_run_id else None)
                ),
                'run_id': m.flow_run_id,
                'created_at': m.created_at.isoformat(),
            }
            for m in rows
        ])


class SendMessageView(APIView):
    parser_classes = [JSONParser, MultiPartParser]

    def post(self, request):
        serializer = SendMessageSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Invalid input.', 'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        image = data.get('image')
        try:
            if image:
                caption = data.get('message', '').strip()
                message_id = send_uploaded_image(
                    data['phone_number'], image, image.name, image.detected_mime, caption
                )
                log_message(
                    MessageLog.OUT, data['phone_number'], 'image',
                    caption or image.name, message_id,
                )
                audit.record(request, 'send', 'message', message_id, data['phone_number'], {'type': 'image'})
            else:
                message_id = send_template_message(data['phone_number'])
                log_message(
                    MessageLog.OUT, data['phone_number'], 'template',
                    settings.WHATSAPP_TEMPLATE_NAME, message_id,
                )
                audit.record(request, 'send', 'message', message_id, data['phone_number'], {'type': 'template'})
        except ConfigurationError as exc:
            return Response(
                {'success': False, 'message': FAIL, 'error': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except WhatsAppError as exc:
            return Response(
                {'success': False, 'message': FAIL, 'error': str(exc)},
                status=exc.status_code,
            )
        return Response(
            {'success': True, 'message': 'Message accepted by Meta.', 'message_id': message_id},
            status=status.HTTP_200_OK,
        )


class TemplateListCreateView(generics.ListCreateAPIView):
    """List saved templates (newest first) and create a new one."""

    queryset = MessageTemplate.objects.all()
    serializer_class = MessageTemplateSerializer
    pagination_class = None

    def perform_create(self, serializer):
        obj = serializer.save()
        audit.record(
            self.request, 'create', 'template', obj.id, obj.name,
            {'name': obj.name, 'description': obj.description},
        )


class TemplateDetailView(generics.RetrieveUpdateDestroyAPIView):
    """View, edit (PATCH/PUT) or delete one saved template and its question flow."""

    queryset = MessageTemplate.objects.all()
    serializer_class = MessageTemplateSerializer

    def get_throttles(self):
        # Limit password guessing on delete (5 attempts a minute).
        if self.request.method == 'DELETE':
            self.throttle_scope = 'admin_delete'
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def perform_update(self, serializer):
        before = {'name': serializer.instance.name, 'description': serializer.instance.description}
        obj = serializer.save()
        changes = audit.diff(before, {'name': obj.name, 'description': obj.description})
        audit.record(self.request, 'update', 'template', obj.id, obj.name, changes)

    def perform_destroy(self, instance):
        info = {
            'name': instance.name, 'description': instance.description,
            'questions': instance.questions.count(),
        }
        pk, label = instance.id, instance.name
        instance.delete()
        audit.record(self.request, 'delete', 'template', pk, label, info)

    def destroy(self, request, *args, **kwargs):
        """Deleting a template also deletes its questions and saved flow, so it needs the
        super admin's password in the request body: {"password": "..."}."""
        password = str(request.data.get('password', ''))
        user = request.user
        if not (user.is_superuser and password and user.check_password(password)):
            return Response(
                {'success': False, 'error': 'Wrong super admin password. Nothing was deleted.'},
                status=status.HTTP_403_FORBIDDEN,  # not 401: the page would log the user out
            )
        return super().destroy(request, *args, **kwargs)
