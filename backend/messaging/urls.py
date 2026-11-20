from django.urls import path

from .flows import (
    FlowImportView,
    FlowSyncView,
    FlowView,
    OptionCreateView,
    OptionDeleteView,
    QuestionCreateView,
    QuestionDeleteView,
    TemplateSendView,
)
from .health import health
from .profile import (
    AvatarView,
    ProfilePasswordChangeView,
    ProfilePasswordOtpView,
    ProfilePasswordVerifyView,
    ProfileView,
)
# DISABLED (public forgot-password API): from .password_reset import ForgotPasswordView, ResetPasswordView, VerifyOtpView
from .users import UserDeleteView, UserListCreateView
from .audit_views import AuditLogListView
from .runs import FlowRunDetailView, FlowRunListView, TemplateExportView, TemplateStatsView
from .views import (
    LoginView,
    LogoutView,
    MeView,
    MessageHistoryView,
    SendMessageView,
    StatsView,
    TemplateDetailView,
    TemplateListCreateView,
)

urlpatterns = [
    path('health/', health, name='health'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/me/', MeView.as_view(), name='me'),
    # DISABLED: these three endpoints let anyone who is not signed in reset an admin password by email code.
    # Turned off so nothing is reachable from outside. Re-enable them together with the import above.
    # path('auth/forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    # path('auth/verify-otp/', VerifyOtpView.as_view(), name='verify-otp'),
    # path('auth/reset-password/', ResetPasswordView.as_view(), name='reset-password'),
    path('users/', UserListCreateView.as_view(), name='users'),
    path('users/<int:user_id>/', UserDeleteView.as_view(), name='user-delete'),
    path('stats/', StatsView.as_view(), name='stats'),
    path('templates/', TemplateListCreateView.as_view(), name='templates'),
    path('templates/<int:pk>/', TemplateDetailView.as_view(), name='template-detail'),
    path('templates/<int:template_id>/send/', TemplateSendView.as_view(), name='template-send'),
    path('templates/<int:template_id>/flow/', FlowView.as_view(), name='flow'),
    path('templates/<int:template_id>/import-flow/', FlowImportView.as_view(), name='flow-import'),
    path('templates/<int:template_id>/sync-flow/', FlowSyncView.as_view(), name='flow-sync'),
    path('templates/<int:template_id>/questions/', QuestionCreateView.as_view(), name='question-create'),
    path('questions/<int:question_id>/options/', OptionCreateView.as_view(), name='option-create'),
    path('questions/<int:question_id>/', QuestionDeleteView.as_view(), name='question-delete'),
    path('options/<int:option_id>/', OptionDeleteView.as_view(), name='option-delete'),
    path('flow-runs/', FlowRunListView.as_view(), name='flow-runs'),
    path('flow-runs/<int:run_id>/', FlowRunDetailView.as_view(), name='flow-run-detail'),
    path('templates/<int:template_id>/stats/', TemplateStatsView.as_view(), name='template-stats'),
    path('templates/<int:template_id>/export/', TemplateExportView.as_view(), name='template-export'),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('profile/avatar/', AvatarView.as_view(), name='profile-avatar'),
    path('profile/password/send-otp/', ProfilePasswordOtpView.as_view(), name='profile-password-otp'),
    path('profile/password/verify-otp/', ProfilePasswordVerifyView.as_view(), name='profile-password-verify'),
    path('profile/password/change/', ProfilePasswordChangeView.as_view(), name='profile-password-change'),
    path('audit-logs/', AuditLogListView.as_view(), name='audit-logs'),
    path('messages/', MessageHistoryView.as_view(), name='message-history'),
    path('send-message/', SendMessageView.as_view(), name='send-message'),
]
