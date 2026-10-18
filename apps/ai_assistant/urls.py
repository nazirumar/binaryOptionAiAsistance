# apps/ai_assistant/urls.py
from __future__ import annotations

from django.urls import path

from apps.ai_assistant import views

app_name = "ai_assistant"

urlpatterns = [
    path("conversations/", views.ConversationListView.as_view(), name="conversation-list"),
    path(
        "conversations/<int:pk>/",
        views.ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path(
        "conversations/<int:pk>/messages/",
        views.ConversationMessageView.as_view(),
        name="conversation-messages",
    ),
    path("analyze/", views.AnalyzeView.as_view(), name="analyze"),
    path("analyses/<int:pk>/", views.AnalysisDetailView.as_view(), name="analysis-detail"),
]
