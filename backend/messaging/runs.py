"""Read-only API over saved template sends ("runs") for the Diagram Templates page."""

from collections import Counter

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .flows import build_flow
from .models import FlowRun, FlowStep, MessageLog, MessageTemplate

DEFAULT_LIMIT = 200


def _template_ref(run):
    if run.template_id:
        return {'id': run.template_id, 'name': run.template.name}
    return {'id': None, 'name': run.template_name}  # template was deleted


def run_summary(run):
    return {
        'id': run.id,
        'template': _template_ref(run),
        'phone_number': run.phone_number,
        'status': run.status,
        'current_question_id': run.current_question_id,
        'current_text': run.current_text,
        'started_at': run.started_at.isoformat(),
        'updated_at': run.updated_at.isoformat(),
        'steps': getattr(run, 'step_count', None),
    }


def filter_runs(rows, params):
    q = params.get('q', '').strip()
    if q:
        cond = Q(template_name__icontains=q) | Q(template__name__icontains=q)
        digits = ''.join(ch for ch in q if ch.isdigit())
        if digits:
            cond |= Q(phone_number__contains=digits)
        rows = rows.filter(cond)
    template = params.get('template', '')
    if template.isdigit():
        rows = rows.filter(template_id=int(template))
    status = params.get('status', '')
    if status in (FlowRun.ACTIVE, FlowRun.COMPLETED, FlowRun.FAILED):
        rows = rows.filter(status=status)
    return rows


class FlowRunListView(APIView):
    """Saved template sends. Filters: ?q= (phone number or template name), ?template=, ?status="""

    def get(self, request):
        rows = FlowRun.objects.select_related('template').annotate(step_count=Count('steps'))
        rows = filter_runs(rows, request.query_params)
        try:
            limit = min(int(request.query_params.get('limit', DEFAULT_LIMIT)), 500)
        except ValueError:
            limit = DEFAULT_LIMIT
        return Response([run_summary(r) for r in rows[:limit]])


class FlowRunDetailView(APIView):
    """One person's journey: every step in order, plus the template diagram with their path."""

    def get(self, request, run_id):
        run = get_object_or_404(FlowRun.objects.select_related('template'), pk=run_id)
        steps = list(run.steps.all())

        wa_ids = [s.wa_message_id for s in steps if s.wa_message_id]
        delivery = {
            m.wa_message_id: m.status
            for m in MessageLog.objects.filter(direction=MessageLog.OUT, wa_message_id__in=wa_ids)
        }

        flow = None
        if run.template_id:
            root, stats = build_flow(run.template)
            flow = {
                'template': {'id': run.template_id, 'name': run.template.name},
                'root': root,
                'stats': stats,
            }

        return Response({
            'run': run_summary(run),
            'steps': [
                {
                    'order': s.order,
                    'kind': s.kind,
                    'text': s.text,
                    'detail': s.detail,
                    'delivery_status': delivery.get(s.wa_message_id, ''),
                    'question_id': s.question_id,
                    'option_id': s.option_id,
                    'created_at': s.created_at.isoformat(),
                }
                for s in steps
            ],
            'flow': flow,
            'path': {
                # ids that still exist in the template; used to highlight the route taken
                'question_ids': [s.question_id for s in steps if s.question_id],
                'option_ids': [s.option_id for s in steps if s.kind == FlowStep.OPTION_TAPPED and s.option_id],
            },
        })


class TemplateStatsView(APIView):
    """Per-template numbers for the diagram: who is where, and how often each option was tapped."""

    def get(self, request, template_id):
        template = get_object_or_404(MessageTemplate, pk=template_id)
        runs = FlowRun.objects.filter(template=template)

        here = Counter(
            runs.filter(status=FlowRun.ACTIVE, current_question__isnull=False)
            .values_list('current_question_id', flat=True)
        )
        taps = Counter(
            FlowStep.objects.filter(run__template=template, kind=FlowStep.OPTION_TAPPED, option__isnull=False)
            .values_list('option_id', flat=True)
        )
        reached = Counter(
            FlowStep.objects.filter(run__template=template, kind=FlowStep.QUESTION_SENT, question__isnull=False)
            .values('question_id', 'run_id')
            .distinct()
            .values_list('question_id', flat=True)
        )
        return Response({
            'runs': runs.count(),
            'active': runs.filter(status=FlowRun.ACTIVE).count(),
            'completed': runs.filter(status=FlowRun.COMPLETED).count(),
            'failed': runs.filter(status=FlowRun.FAILED).count(),
            'users_here': {str(k): v for k, v in here.items()},
            'reached': {str(k): v for k, v in reached.items()},
            'option_taps': {str(k): v for k, v in taps.items()},
        })
