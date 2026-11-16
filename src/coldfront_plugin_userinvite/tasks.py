"""
Django-Q tasks for the userinvite plugin.
"""

from coldfront_plugin_userinvite.models import Invitation


def expire_stale_invitations():
    """Mark all pending invitations that have passed their expiry time as expired."""
    expired_count = 0
    pending = Invitation.objects.filter(status=Invitation.Status.PENDING)
    for invitation in pending:
        if invitation.is_expired:
            invitation.status = Invitation.Status.EXPIRED
            invitation.save(update_fields=["status"])
            expired_count += 1
    return f"Expired {expired_count} stale invitation(s)."
