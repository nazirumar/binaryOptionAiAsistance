"""Abstract base models reused by concrete models across the project.

Every domain model should inherit from :class:`TimeStampedModel` and, when a
non-guessable identifier is desirable, :class:`UUIDModel`.
"""

from __future__ import annotations

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Adds self-managed ``created_at`` / ``updated_at`` timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """Uses a UUID primary key instead of a sequential integer."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class UUIDTimeStampedModel(UUIDModel, TimeStampedModel):
    """Convenience combination of UUID primary key and timestamps."""

    class Meta:
        abstract = True
