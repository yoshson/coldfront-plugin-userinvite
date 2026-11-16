from django.contrib import admin

from coldfront_plugin_userinvite.models import Invitation


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "project",
        "role",
        "status",
        "invited_by",
        "created",
        "accepted_at",
    )
    list_filter = ("status", "project", "role")
    search_fields = ("email", "project__title")
    readonly_fields = ("token", "created", "accepted_at", "accepted_by")
    raw_id_fields = ("project", "invited_by", "accepted_by")
