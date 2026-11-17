from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import SendMessageSerializer
from .services import ConfigurationError, WhatsAppError, send_text_message

FAIL = 'Unable to send WhatsApp message.'


class SendMessageView(APIView):
    def post(self, request):
        serializer = SendMessageSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Invalid input.', 'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        try:
            message_id = send_text_message(data['phone_number'], data['message'])
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
