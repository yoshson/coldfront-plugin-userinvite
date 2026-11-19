"""Data model for project invitations.

An invitation records the email address, project and role together with
the random token that accept links are signed from, plus its lifecycle
status and acceptance details.
"""

import secrets
from datetime import timedelta
from typing import ClassVar

from django.conf import settings
from django.core.signing import TimestampSigner
from django.db import models
from django.utils import timezone


class Invitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        EXPIRED = "expired", "Expired"
        REVOKED = "revoked", "Revoked"
        REDUNDANT = "redundant", "Redundant"

    email = models.EmailField(help_text="Email address the invitation was sent to.")
    project = models.ForeignKey(
        "project.Project",
        on_delete=models.CASCADE,
        related_name="invitations",
        help_text="Project the invitation grants access to.",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_invitations",
        help_text="User who sent the invitation.",
    )
    role = models.ForeignKey(
        "project.ProjectUserRoleChoice",
        on_delete=models.CASCADE,
        help_text="Role the invitee receives on acceptance.",
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Random per-invitation token; accept URLs contain a signed form.",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Current lifecycle state of the invitation.",
    )
    created = models.DateTimeField(
        auto_now_add=True, help_text="When the invitation was created."
    )
    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the invitation was accepted or found redundant.",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accepted_invitations",
        help_text="Account that accepted the invitation.",
    )

    class Meta:
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["email", "project"],
                condition=models.Q(status="pending"),
                name="unique_pending_invite_per_email_project",
            )
        ]
        ordering: ClassVar[list] = ["-created"]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(48)  # 64 chars, 384 bits
        super().save(*args, **kwargs)

    @property
    def max_age(self):
        """Maximum age of a signed link, in seconds."""
        return getattr(settings, "USERINVITE_LINK_EXPIRY_SECONDS", 604800)

    @property
    def is_expired(self):
        """Whether the invitation has outlived the signed-link lifetime."""
        return timezone.now() > self.created + timedelta(seconds=self.max_age)

    def get_signed_token(self):
        """Return a signed, timestamped token for use in the invite URL."""
        return TimestampSigner().sign(self.token)

    @classmethod
    def from_signed_token(cls, signed_value):
        """Look up an invitation by its signed token.
        Raises SignatureExpired or BadSignature on failure."""
        max_age = getattr(settings, "USERINVITE_LINK_EXPIRY_SECONDS", 604800)
        token = TimestampSigner().unsign(signed_value, max_age=max_age)
        return cls.objects.get(token=token, status=cls.Status.PENDING)

    def __str__(self):
        return f"Invite {self.email} → {self.project} ({self.status})"
