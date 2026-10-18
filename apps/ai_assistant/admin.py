# apps/ai_assistant/admin.py
from __future__ import annotations

from django.contrib import admin

from apps.ai_assistant.models import (
    AIAnalysisSession,
    AIAttachment,
    AIConversation,
    AIMessage,
    AIResponseAudit,
    AssistantConfiguration,
)

admin.site.register(AIConversation)
admin.site.register(AIMessage)
admin.site.register(AIAnalysisSession)
admin.site.register(AIAttachment)
admin.site.register(AIResponseAudit)
admin.site.register(AssistantConfiguration)
