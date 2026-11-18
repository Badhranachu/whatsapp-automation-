"""Question flows: each template holds a tree of questions -> options -> questions ..."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FlowRun, FlowStep, MessageTemplate, Option, Question, add_step

MAX_OPTIONS = 3  # WhatsApp reply buttons: at most 3 per message
MAX_TITLE = 20  # button title limit
MAX_TEXT = 1024  # question text limit
MAX_DEPTH = 50  # guards against absurdly deep trees


def _bad(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({'success': False, 'error': message}, status=code)


def _depth_of(question):
    """1 for the root question, 2 for a question under its option, and so on."""
    depth = 1
    while question.parent_option_id:
        question = question.parent_option.question
        depth += 1
    return depth


def build_flow(template):
    """Return (tree, stats) for a template using two queries, however deep it is."""
    questions = list(Question.objects.filter(template=template))
    options = list(Option.objects.filter(question__template=template))

    options_by_question = {}
    for o in options:
        options_by_question.setdefault(o.question_id, []).append(o)
    question_for_option = {q.parent_option_id: q for q in questions if q.parent_option_id}

    max_depth = 0

    def node(q, depth):
        nonlocal max_depth
        max_depth = max(max_depth, depth)
        return {
            'id': q.id,
            'text': q.text,
            'depth': depth,
            'options': [
                {
                    'id': o.id,
                    'title': o.title,
                    'next': node(question_for_option[o.id], depth + 1)
                    if o.id in question_for_option
                    else None,
                }
                for o in options_by_question.get(q.id, [])
            ],
        }

    root_question = next((q for q in questions if not q.parent_option_id), None)
    root = node(root_question, 1) if root_question else None
    stats = {'questions': len(questions), 'options': len(options), 'depth': max_depth}
    return root, stats


class FlowView(APIView):
    def get(self, request, template_id):
        template = get_object_or_404(MessageTemplate, pk=template_id)
        root, stats = build_flow(template)
        return Response({
            'template': {'id': template.id, 'name': template.name, 'description': template.description},
            'root': root,
            'stats': stats,
        })


def _clean_titles(raw):
    """Validate a list of option titles. Returns (titles, error)."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, 'Options must be a list.'
    if len(raw) > MAX_OPTIONS:
        return None, f'A question can have at most {MAX_OPTIONS} options (WhatsApp button limit).'
    titles, seen = [], set()
    for item in raw:
        title = str(item).strip()
        if not title:
            return None, 'Every option needs text.'
        if len(title) > MAX_TITLE:
            return None, f'Option text must be {MAX_TITLE} characters or fewer (WhatsApp button limit).'
        if title.casefold() in seen:
            return None, 'Options must be different from each other.'
        seen.add(title.casefold())
        titles.append(title)
    return titles, None


class QuestionCreateView(APIView):
    """Add the first question (no option_id) or a question under an option.

    An optional `options` list creates the question's options in the same request
    (all or nothing).
    """

    def post(self, request, template_id):
        template = get_object_or_404(MessageTemplate, pk=template_id)
        text = str(request.data.get('text', '')).strip()
        if not text:
            return _bad('Question text is required.')
        if len(text) > MAX_TEXT:
            return _bad(f'Question must be {MAX_TEXT} characters or fewer.')
        titles, error = _clean_titles(request.data.get('options'))
        if error:
            return _bad(error)

        option_id = request.data.get('option_id')
        parent = None
        if option_id in (None, ''):
            if Question.objects.filter(template=template, parent_option__isnull=True).exists():
                return _bad('This template already has a first question.')
        else:
            parent = Option.objects.filter(pk=option_id, question__template=template).first()
            if not parent:
                return _bad('Option not found in this template.', status.HTTP_404_NOT_FOUND)
            if Question.objects.filter(parent_option=parent).exists():
                return _bad('This option already leads to a question.')
            if _depth_of(parent.question) >= MAX_DEPTH:
                return _bad(f'Flows can be at most {MAX_DEPTH} questions deep.')

        with transaction.atomic():
            q = Question.objects.create(template=template, text=text, parent_option=parent)
            for title in titles:
                Option.objects.create(question=q, title=title)
        return Response({'id': q.id, 'text': q.text}, status=status.HTTP_201_CREATED)


def _title_error(question, title, exclude_id=None):
    """Return an error message if `title` is not allowed for an option of `question`."""
    if not title:
        return 'Option text is required.'
    if len(title) > MAX_TITLE:
        return f'Option text must be {MAX_TITLE} characters or fewer (WhatsApp button limit).'
    clash = question.options.filter(title__iexact=title)
    if exclude_id:
        clash = clash.exclude(pk=exclude_id)
    if clash.exists():
        return 'This question already has an option with that text.'
    return None


class OptionCreateView(APIView):
    def post(self, request, question_id):
        question = get_object_or_404(Question, pk=question_id)
        title = str(request.data.get('title', '')).strip()
        if question.options.count() >= MAX_OPTIONS and title:
            return _bad(f'A question can have at most {MAX_OPTIONS} options (WhatsApp button limit).')
        error = _title_error(question, title)
        if error:
            return _bad(error)
        o = Option.objects.create(question=question, title=title)
        return Response({'id': o.id, 'title': o.title}, status=status.HTTP_201_CREATED)


class QuestionDeleteView(APIView):
    """Edit (PATCH text) or delete a question."""

    def patch(self, request, question_id):
        question = get_object_or_404(Question, pk=question_id)
        text = str(request.data.get('text', '')).strip()
        if not text:
            return _bad('Question text is required.')
        if len(text) > MAX_TEXT:
            return _bad(f'Question must be {MAX_TEXT} characters or fewer.')
        question.text = text
        question.save(update_fields=['text'])
        return Response({'id': question.id, 'text': question.text})

    def delete(self, request, question_id):
        get_object_or_404(Question, pk=question_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OptionDeleteView(APIView):
    """Edit (PATCH title) or delete an option."""

    def patch(self, request, option_id):
        option = get_object_or_404(Option, pk=option_id)
        title = str(request.data.get('title', '')).strip()
        error = _title_error(option.question, title, exclude_id=option.id)
        if error:
            return _bad(error)
        option.title = title
        option.save(update_fields=['title'])
        return Response({'id': option.id, 'title': option.title})

    def delete(self, request, option_id):
        get_object_or_404(Option, pk=option_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


FLOW_BUTTON_PREFIX = 'flow_opt_'


def send_question(to, question, run=None):
    """Send a flow question: reply buttons when it has options, plain text otherwise.

    Logs the message (tagged with its template and run) and, when a run is given, records
    the step and moves the run to this question. Returns the Meta message id.
    """
    from .models import FlowRun, FlowStep, MessageLog, add_step, log_message
    from .services import send_buttons_message, send_text_message

    options = list(question.options.all())
    if options:
        message_id = send_buttons_message(
            to,
            question.text,
            [{'id': f'{FLOW_BUTTON_PREFIX}{o.id}', 'title': o.title} for o in options],
        )
    else:
        message_id = send_text_message(to, question.text)
    log_message(
        MessageLog.OUT, to, 'flow', question.text, message_id,
        template=question.template, flow_run=run,
    )
    if run is not None:
        add_step(
            run, FlowStep.QUESTION_SENT, question=question, text=question.text, wa_message_id=message_id
        )
        run.current_question = question
        run.current_text = question.text
        # A message with no options is an end note: the flow is finished for this person.
        run.status = FlowRun.ACTIVE if options else FlowRun.COMPLETED
        run.save()
    return message_id


MAX_RECIPIENTS = 50


class TemplateSendView(APIView):
    """Send a template's first question (with its options as buttons) to one or more numbers.

    Body: {"phone_numbers": ["+91 98765 43210", ...]} (a single "phone_number" also works).
    Every number is validated first; nothing is sent if any is invalid. Each number is then
    sent separately and gets its own result, so one failure doesn't stop the rest.
    """

    def post(self, request, template_id):
        from .serializers import SendMessageSerializer
        from .services import ConfigurationError, WhatsAppError

        template = get_object_or_404(MessageTemplate, pk=template_id)

        raw = request.data.get('phone_numbers')
        if raw is None:
            raw = [request.data.get('phone_number', '')]
        if not isinstance(raw, list) or not raw:
            return _bad('Add at least one phone number.')
        if len(raw) > MAX_RECIPIENTS:
            return _bad(f'You can send to at most {MAX_RECIPIENTS} numbers at a time.')

        numbers, invalid = [], []
        for item in raw:
            ser = SendMessageSerializer(data={'phone_number': str(item)})
            if ser.is_valid():
                number = ser.validated_data['phone_number']
                if number not in numbers:  # same number typed twice is sent once
                    numbers.append(number)
            else:
                invalid.append(str(item))
        if invalid:
            return Response(
                {
                    'success': False,
                    'message': 'Invalid input.',
                    'error': 'These numbers are not valid: ' + ', '.join(invalid),
                    'invalid': invalid,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        root = Question.objects.filter(template=template, parent_option__isnull=True).first()
        if not root:
            return _bad('This template has no questions yet. Add them in the Questions tab first.')

        results = []
        for number in numbers:
            run = FlowRun.objects.create(
                template=template, template_name=template.name, phone_number=number
            )
            try:
                message_id = send_question(number, root, run)
                results.append(
                    {'phone_number': number, 'success': True, 'message_id': message_id, 'run_id': run.id}
                )
            except (ConfigurationError, WhatsAppError) as exc:
                add_step(run, FlowStep.SEND_FAILED, question=root, text=root.text, detail=str(exc))
                run.status = FlowRun.FAILED
                run.current_question = root
                run.current_text = root.text
                run.save()
                results.append(
                    {'phone_number': number, 'success': False, 'error': str(exc), 'run_id': run.id}
                )
        sent = sum(1 for r in results if r['success'])
        return Response({
            'success': sent == len(results),
            'message': f'{sent} of {len(results)} accepted by Meta.',
            'sent': sent,
            'failed': len(results) - sent,
            'results': results,
        })
