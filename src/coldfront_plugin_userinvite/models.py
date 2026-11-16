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

    email = models.EmailField()
    project = models.ForeignKey(
        "project.Project", on_delete=models.CASCADE, related_name="invitations"
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_invitations",
    )
    role = models.ForeignKey("project.ProjectUserRoleChoice", on_delete=models.CASCADE)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    created = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accepted_invitations",
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
        return getattr(settings, "USERINVITE_LINK_EXPIRY_SECONDS", 604800)

    @property
    def is_expired(self):
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
