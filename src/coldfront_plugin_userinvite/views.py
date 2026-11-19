"""Views for sending, managing and accepting project invitations.

The manager-facing views (send/list/revoke/resend) return HTML fragments
for htmx swaps. ``AcceptInviteView`` is public: anonymous visitors are sent
through ColdFront's login and resume via the ``next`` parameter. The signed
link is the only credential; acceptance does not match the logged-in
account's email address against the invitation's.
"""

import logging

from coldfront.core.project.models import (
    Project,
    ProjectUser,
)
from coldfront.core.utils.common import import_from_settings
from coldfront.core.utils.mail import (
    build_link,
    email_template_context,
    send_email_template,
)
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.signing import BadSignature, SignatureExpired
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views import View

from coldfront_plugin_userinvite.forms import InviteUsersForm
from coldfront_plugin_userinvite.models import Invitation

logger = logging.getLogger(__name__)

# Read at import time, like ColdFront's own views; changes require a
# process restart (tests patch these module constants instead).
EMAIL_ENABLED = import_from_settings("EMAIL_ENABLED", False)
if EMAIL_ENABLED:
    EMAIL_SENDER = import_from_settings("EMAIL_SENDER")


def _send_invite_email(invitation, project):
    """Generate a signed link and send the invitation email."""
    if not EMAIL_ENABLED:
        return
    signed_token = invitation.get_signed_token()
    invite_url = build_link(
        reverse("userinvite-accept", kwargs={"signed_token": signed_token})
    )
    pi = project.pi
    if pi.first_name and pi.last_name:
        pi_name = f"{pi.first_name} {pi.last_name}"
    else:
        pi_name = pi.username

    inviter = invitation.invited_by
    if inviter.first_name or inviter.last_name:
        inviter_name = f"{inviter.first_name} {inviter.last_name}".strip()
    else:
        inviter_name = inviter.username

    ctx = email_template_context()
    ctx.update(
        {
            "project_title": project.title,
            "pi_name": pi_name,
            "role": invitation.role.name,
            "invite_url": invite_url,
            "expiry_days": getattr(settings, "USERINVITE_LINK_EXPIRY_SECONDS", 604800)
            // 86400,
            "inviter_name": inviter_name,
        }
    )
    send_email_template(
        subject=f"Invitation to join project: {project.title}",
        template_name="userinvite/email/invite_email.txt",
        template_context=ctx,
        sender=EMAIL_SENDER,
        receiver_list=[invitation.email],
    )


def _expire_stale_invitations(project):
    """Lazily mark stale pending invitations as expired."""
    for inv in Invitation.objects.filter(
        project=project, status=Invitation.Status.PENDING
    ):
        if inv.is_expired:
            inv.status = Invitation.Status.EXPIRED
            inv.save(update_fields=["status"])


def invite_context(project, show_all=False):
    """Shared context for the invite form and the invitations table.

    show_all=False (default): only PENDING invitations are shown.
    show_all=True: full history is shown.
    """
    _expire_stale_invitations(project)
    all_invitations = Invitation.objects.filter(project=project)
    return {
        "project": project,
        "invite_form": InviteUsersForm(),
        "invitations": all_invitations
        if show_all
        else all_invitations.filter(status=Invitation.Status.PENDING),
        "has_history": all_invitations.exclude(
            status=Invitation.Status.PENDING
        ).exists(),
        "show_all": show_all,
    }


def _render_invite_table(
    request, project, show_all=False, status_message="", is_error=False
):
    """Render the invitation table fragment (history toggle, revoke, resend)."""
    ctx = invite_context(project, show_all=show_all)
    ctx.update(
        {
            "invite_table_status_message": status_message,
            "invite_table_is_error": is_error,
        }
    )
    html = render_to_string(
        "userinvite/_invite_table.html",
        ctx,
        request=request,
    )
    return HttpResponse(html)


def _render_invite_section(request, project, status_message="", is_error=False):
    """Render the invite section fragment (form + message + table).

    Used as the response to the invite form's htmx POST.
    """
    ctx = invite_context(project)
    ctx.update(
        {
            "invite_form_status_message": status_message,
            "invite_form_is_error": is_error,
        }
    )
    html = render_to_string(
        "userinvite/invite_section.html",
        ctx,
        request=request,
    )
    return HttpResponse(html)


class _ProjectManagerTestMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Shared permission check: user must be PI, Manager, or superuser."""

    def test_func(self):
        if self.request.user.is_superuser:
            return True
        project = get_object_or_404(Project, pk=self.kwargs.get("pk"))
        if project.pi == self.request.user:
            return True
        return project.projectuser_set.filter(
            user=self.request.user, role__name="Manager", status__name="Active"
        ).exists()


class InviteUsersMixin:
    """Mixin to add to the ProjectAddUsersSearchView.

    Provides invite_form + invitations list in context.
    GET-only — the invite form submits via htmx to InviteUsersView.
    """

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context.update(invite_context(context["project"]))
        return context


class InviteUsersView(_ProjectManagerTestMixin, View):
    """POST: validate invite form, create Invitation records, send emails.
    Returns an HTML fragment (invite_section.html) for htmx swap."""

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        form = InviteUsersForm(request.POST)
        if not form.is_valid():
            # Re-render with form errors
            ctx = invite_context(project)
            ctx["invite_form"] = form  # bound form with errors
            html = render_to_string(
                "userinvite/invite_section.html",
                ctx,
                request=request,
            )
            return HttpResponse(html)

        emails = form.cleaned_data["emails"]
        role = form.cleaned_data["role"]
        created = 0
        skipped = []
        for email in emails:
            if project.projectuser_set.filter(
                user__email=email, status__name="Active"
            ).exists():
                skipped.append(f"{email} (already in project)")
                continue
            if Invitation.objects.filter(
                email=email,
                project=project,
                status=Invitation.Status.PENDING,
            ).exists():
                skipped.append(f"{email} (invite already pending)")
                continue

            invitation = Invitation.objects.create(
                email=email,
                project=project,
                invited_by=request.user,
                role=role,
            )
            _send_invite_email(invitation, project)
            created += 1

        parts = []
        if created:
            parts.append(f"Sent {created} invitation(s).")
        if skipped:
            parts.append(f"Skipped: {'; '.join(skipped)}")
        return _render_invite_section(
            request,
            project,
            status_message=" ".join(parts) or "No invitations sent.",
        )


class InviteListView(_ProjectManagerTestMixin, View):
    """GET: return the invite table as an HTML fragment."""

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        show_all = request.GET.get("show_all") == "1"
        return _render_invite_table(request, project, show_all=show_all)


class AcceptInviteView(View):
    """Public view — handles the invite link click.

    The signed link is the only credential: acceptance does not compare
    ``request.user.email`` with the invitation's email address.
    """

    def get(self, request, signed_token):
        try:
            invitation = Invitation.from_signed_token(signed_token)
        except SignatureExpired:
            messages.error(request, "This invitation link has expired.")
            return redirect("home")
        except (BadSignature, Invitation.DoesNotExist):
            messages.error(request, "Invalid or already used invitation link.")
            return redirect("home")

        if not request.user.is_authenticated:
            # Login resumes the flow through the next URL, which points
            # back at this signed accept link.
            login_url = reverse("login")
            next_url = reverse(
                "userinvite-accept", kwargs={"signed_token": signed_token}
            )
            return redirect(f"{login_url}?next={next_url}")

        # User is authenticated — add to project
        project = invitation.project
        user = request.user

        # Check if already in project
        if project.projectuser_set.filter(user=user, status__name="Active").exists():
            invitation.status = Invitation.Status.REDUNDANT
            invitation.accepted_at = timezone.now()
            invitation.accepted_by = user
            invitation.save()

            role_updated = False
            old_role = None
            new_role = invitation.role.name
            try:
                project_user = ProjectUser.objects.get(user=user, project=project)
                if (
                    project_user.role != invitation.role
                    and project_user.user != project.pi
                ):
                    role_updated = True
                    old_role = project_user.role.name
                    project_user.role = invitation.role
                    project_user.save(update_fields=["role"])
            except ProjectUser.DoesNotExist:
                pass

            # Compose unified info message
            msg = f"You are already a member of project '{project.title}'."
            if role_updated:
                msg += f" However, your role has been updated from '{old_role}' to '{new_role}'."
            messages.info(request, msg)
            return redirect("project-detail", pk=project.pk)

        # Add user to project. Project.add_user has the same
        # update-or-create semantics (a returning member's Removed row
        # is reactivated, role and status set) and, unlike a direct
        # ProjectUser write, broadcasts the project_activate_user
        # signal -- so downstream integrations (allocation membership
        # sync, PI/manager notifications) see the new member too.
        project.add_user(user, invitation.role)

        invitation.status = Invitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.accepted_by = user
        invitation.save()

        messages.success(
            request,
            f"You have been added to project '{project.title}' as "
            f"{invitation.role.name}.",
        )
        return redirect("project-detail", pk=project.pk)


class RevokeInviteView(_ProjectManagerTestMixin, View):
    """POST: revoke a pending invitation. Returns HTML fragment for htmx."""

    def post(self, request, pk, invite_pk):
        invitation = get_object_or_404(
            Invitation,
            pk=invite_pk,
            project__pk=pk,
            status=Invitation.Status.PENDING,
        )
        invitation.status = Invitation.Status.REVOKED
        invitation.save(update_fields=["status"])
        return _render_invite_table(
            request,
            invitation.project,
            status_message=f"Invitation to {invitation.email} revoked.",
        )


class ResendInviteView(_ProjectManagerTestMixin, View):
    """POST: revoke the old invitation, create a fresh one, re-send email.
    Returns HTML fragment for htmx."""

    def post(self, request, pk, invite_pk):
        old_invitation = get_object_or_404(
            Invitation,
            pk=invite_pk,
            project__pk=pk,
            status=Invitation.Status.PENDING,
        )
        project = old_invitation.project

        # Revoke the old invitation (invalidates the old link)
        old_invitation.status = Invitation.Status.REVOKED
        old_invitation.save(update_fields=["status"])

        # Create a fresh invitation with a new token and new expiry
        new_invitation = Invitation.objects.create(
            email=old_invitation.email,
            project=project,
            invited_by=request.user,
            role=old_invitation.role,
        )
        _send_invite_email(new_invitation, project)

        return _render_invite_table(
            request,
            project,
            status_message=f"New invitation sent to {new_invitation.email}.",
        )
