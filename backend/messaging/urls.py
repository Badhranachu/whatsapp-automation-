from django.urls import path

from .flows import (
    FlowView,
    OptionCreateView,
    OptionDeleteView,
    QuestionCreateView,
    QuestionDeleteView,
    TemplateSendView,
)
from .runs import FlowRunDetailView, FlowRunListView, TemplateStatsView
from .views import (
    LoginView,
    LogoutView,
    MeView,
    MessageHistoryView,
    SendMessageView,
    SendOptionsView,
    StatsView,
    TemplateDetailView,
    TemplateListCreateView,
)

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/me/', MeView.as_view(), name='me'),
    path('stats/', StatsView.as_view(), name='stats'),
    path('templates/', TemplateListCreateView.as_view(), name='templates'),
    path('templates/<int:pk>/', TemplateDetailView.as_view(), name='template-detail'),
    path('templates/<int:template_id>/send/', TemplateSendView.as_view(), name='template-send'),
    path('templates/<int:template_id>/flow/', FlowView.as_view(), name='flow'),
    path('templates/<int:template_id>/questions/', QuestionCreateView.as_view(), name='question-create'),
    path('questions/<int:question_id>/options/', OptionCreateView.as_view(), name='option-create'),
    path('questions/<int:question_id>/', QuestionDeleteView.as_view(), name='question-delete'),
    path('options/<int:option_id>/', OptionDeleteView.as_view(), name='option-delete'),
    path('flow-runs/', FlowRunListView.as_view(), name='flow-runs'),
    path('flow-runs/<int:run_id>/', FlowRunDetailView.as_view(), name='flow-run-detail'),
    path('templates/<int:template_id>/stats/', TemplateStatsView.as_view(), name='template-stats'),
    path('messages/', MessageHistoryView.as_view(), name='message-history'),
    path('send-options/', SendOptionsView.as_view(), name='send-options'),
    path('send-message/', SendMessageView.as_view(), name='send-message'),
]
