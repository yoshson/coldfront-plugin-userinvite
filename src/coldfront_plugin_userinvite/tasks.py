"""Django-Q task that expires invitations past their link lifetime.

Register it once with the ``add_userinvite_scheduled_tasks`` management
command; the ``expire_stale_invitations`` command calls the same function
for manual or cron-style sweeps.
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
