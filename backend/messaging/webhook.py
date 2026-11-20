import hashlib
import hmac
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .flows import FLOW_BUTTON_PREFIX, send_question
from .models import FlowRun, FlowStep, MessageLog, Option, Question, add_step, log_message, update_status
from .services import ConfigurationError, WhatsAppError, send_image_message, send_text_message

logger = logging.getLogger(__name__)


def _signature_ok(request):
    """Validate X-Hub-Signature-256 when an app secret is configured."""
    secret = settings.WHATSAPP_APP_SECRET
    if not secret:
        return True  # local dev without a secret; set WHATSAPP_APP_SECRET in production
    header = request.headers.get('X-Hub-Signature-256', '')
    expected = 'sha256=' + hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header, expected)


def _extract_incoming(payload):
    """Yield (sender, message_type, content, wa_id, button_id) for each incoming message.

    button_id is the id of the tapped reply button, or None for other messages.
    """
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            for msg in change.get('value', {}).get('messages', []):
                sender = msg.get('from')
                if not sender:
                    continue
                wa_id = msg.get('id', '')
                if msg.get('type') == 'interactive':
                    reply = msg.get('interactive', {}).get('button_reply')
                    if reply and reply.get('title'):
                        yield sender, 'button_reply', reply['title'], wa_id, reply.get('id') or ''
                elif msg.get('type') == 'text':
                    yield sender, 'text', msg.get('text', {}).get('body', ''), wa_id, None


def _apply_statuses(payload):
    """Record delivery status updates (sent/delivered/read/failed) for our messages."""
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            for st in change.get('value', {}).get('statuses', []):
                wa_id, status = st.get('id'), st.get('status')
                if not wa_id or not status:
                    continue
                detail = ''
                errors = st.get('errors') or []
                if errors:
                    e = errors[0]
                    detail = f"({e.get('code')}) {e.get('title') or e.get('message') or ''}".strip()
                    extra = (e.get('error_data') or {}).get('details')
                    if extra:
                        detail += f' - {extra}'
                update_status(wa_id, status, detail)


REPLY_WINDOW = timedelta(hours=24)  # WhatsApp only allows free-form messages inside this window


def _save_reply(sender, text, wa_id, row):
    """A typed message arrived: if it answers a closing message that asks for one, save it.

    Only the latest run of this number counts, only once per run, and only while that run is
    sitting on a closing message with "wants a typed reply" switched on.
    """
    text = text.strip()
    if not text:
        return
    if wa_id and FlowStep.objects.filter(kind=FlowStep.REPLY_RECEIVED, wa_message_id=wa_id).exists():
        return  # Meta re-delivered the same webhook
    run = FlowRun.objects.filter(phone_number=sender).select_related('current_question', 'template').first()
    if not run or run.status != FlowRun.COMPLETED:
        return
    question = run.current_question
    if not question or not question.wants_reply or question.options.exists():
        return
    if run.updated_at < timezone.now() - REPLY_WINDOW:
        return
    if run.steps.filter(kind=FlowStep.REPLY_RECEIVED).exists():
        return  # one reply per run
    add_step(run, FlowStep.REPLY_RECEIVED, question=question, text=text[:4096], wa_message_id=wa_id)
    if row is not None:
        row.template = run.template
        row.flow_run = run
        row.save(update_fields=['template', 'flow_run'])
    if question.reply_thanks:
        try:
            thanks_id = send_text_message(sender, question.reply_thanks)
            log_message(
                MessageLog.OUT, sender, 'flow', question.reply_thanks, thanks_id,
                template=run.template, flow_run=run,
            )
        except (WhatsAppError, ConfigurationError) as exc:
            logger.warning('Could not send the thank-you for a saved reply: %s', exc)


def _continue_flow(sender, button_id, tap_wa_id):
    """A flow button was tapped: record it, then send the sub question under that option.

    Returns the FlowRun the tap belongs to (or None if it should be ignored).
    """
    try:
        option_id = int(button_id[len(FLOW_BUTTON_PREFIX):])
    except ValueError:
        return None
    option = Option.objects.select_related('question__template').filter(pk=option_id).first()
    if not option:
        return None
    if tap_wa_id and FlowStep.objects.filter(
        kind=FlowStep.OPTION_TAPPED, wa_message_id=tap_wa_id
    ).exists():
        return None  # Meta re-delivered the same webhook: don't record or answer twice

    template = option.question.template
    runs = FlowRun.objects.filter(phone_number=sender, template=template, status=FlowRun.ACTIVE)
    run = (
        runs.filter(current_question=option.question).first()
        or runs.first()
        or FlowRun.objects.create(
            template=template, template_name=template.name, phone_number=sender
        )
    )
    add_step(
        run, FlowStep.OPTION_TAPPED,
        question=option.question, option=option, text=option.title, wa_message_id=tap_wa_id,
    )

    nxt = Question.objects.filter(parent_option=option).first()
    if nxt is None:
        # No sub question under this answer: the flow ends here.
        run.status = FlowRun.COMPLETED
        run.save()
        return run
    try:
        send_question(sender, nxt, run)
    except (WhatsAppError, ConfigurationError) as exc:
        add_step(run, FlowStep.SEND_FAILED, question=nxt, text=nxt.text, detail=str(exc))
        run.status = FlowRun.FAILED
        run.save()
        logger.warning('Could not send the next flow question: %s', exc)
    return run


@csrf_exempt
def webhook(request):
    if request.method == 'GET':
        # Meta verification handshake.
        token = settings.WHATSAPP_VERIFY_TOKEN
        if (
            token
            and request.GET.get('hub.mode') == 'subscribe'
            and hmac.compare_digest(request.GET.get('hub.verify_token', ''), token)
        ):
            return HttpResponse(request.GET.get('hub.challenge', ''), content_type='text/plain')
        return HttpResponseForbidden('Verification failed.')

    if request.method == 'POST':
        if not _signature_ok(request):
            return HttpResponseForbidden('Invalid signature.')
        try:
            payload = json.loads(request.body or b'{}')
        except ValueError:
            return HttpResponse(status=400)
        _apply_statuses(payload)
        for sender, msg_type, content, wa_id, button_id in _extract_incoming(payload):
            row = log_message(MessageLog.IN, sender, msg_type, content, wa_id)
            if button_id is None:
                if msg_type == 'text':
                    try:
                        _save_reply(sender, content, wa_id, row)
                    except Exception:  # noqa: BLE001  never fail the webhook over a reply
                        logger.exception('Could not save a typed reply')
                continue
            try:
                if button_id.startswith(FLOW_BUTTON_PREFIX):
                    run = _continue_flow(sender, button_id, wa_id)
                    if run is not None and row is not None:
                        row.template = run.template
                        row.flow_run = run
                        row.save(update_fields=['template', 'flow_run'])
                else:
                    # The fixed demo question: answer with the reply image.
                    reply_id = send_image_message(sender)
                    log_message(MessageLog.OUT, sender, 'image', 'image.png', reply_id)
            except (WhatsAppError, ConfigurationError) as exc:
                # Always return 200 so Meta doesn't retry endlessly.
                logger.warning('Could not send reply to option choice: %s', exc)
        return HttpResponse(status=200)

    return HttpResponse(status=405)
