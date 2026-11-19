"""End-to-end invite flow against the real ColdFront views.

Covers the full lifecycle: sending invitations (with the skips for
duplicate/pending/member addresses), the invitation email with its signed
one-time link, accepting it (new member, already-member, expired and
invalid links, unauthenticated redirects), and revoking/resending.
"""

import pytest
from coldfront.core.project.models import (
    ProjectUser,
    ProjectUserRoleChoice,
    ProjectUserStatusChoice,
)
from coldfront.core.project.signals import project_activate_user
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from coldfront_plugin_userinvite.models import Invitation
from coldfront_plugin_userinvite.views import AcceptInviteView

pytestmark = pytest.mark.django_db

ACCEPT_URL = "userinvite-accept"
SEND_URL = "userinvite-send"
LIST_URL = "userinvite-list"


def role_pk(name="User"):
    return ProjectUserRoleChoice.objects.get(name=name).pk


def create_invitation(
    project, email="invitee@example.org", role="User", invited_by=None
):
    return Invitation.objects.create(
        email=email,
        project=project,
        invited_by=invited_by or project.pi,
        role=ProjectUserRoleChoice.objects.get(name=role),
    )


def post_invite(client, project, emails="invitee@example.org", role=None):
    return client.post(
        reverse(SEND_URL, kwargs={"pk": project.pk}),
        {"emails": emails, "role": role if role is not None else role_pk()},
    )


# ── Sending invitations ─────────────────────────────────────────────────────


def test_pi_can_send_invitation(pi_client, project):
    response = post_invite(pi_client, project)
    assert response.status_code == 200

    invitation = Invitation.objects.get(project=project)
    assert invitation.email == "invitee@example.org"
    assert invitation.status == Invitation.Status.PENDING
    assert invitation.invited_by == project.pi
    assert invitation.token  # generated on save


def test_manager_can_send_invitation(manager_client, project):
    assert post_invite(manager_client, project).status_code == 200
    assert Invitation.objects.filter(project=project).exists()


def test_outsider_cannot_send_invitation(outsider_client, project):
    response = post_invite(outsider_client, project)
    assert response.status_code == 403
    assert not Invitation.objects.filter(project=project).exists()


def test_anonymous_user_is_redirected_to_login(client, project):
    response = post_invite(client, project)
    assert response.status_code == 302
    assert reverse("login") in response.url


def test_invitation_email_contains_signed_link(pi_client, project):
    post_invite(pi_client, project)

    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    invitation = Invitation.objects.get(project=project)
    # send_email_template prefixes the subject with EMAIL_SUBJECT_PREFIX.
    assert email.subject == (f"[ColdFront] Invitation to join project: {project.title}")
    assert email.to == ["invitee@example.org"]
    signed_token = invitation.get_signed_token()
    assert signed_token in email.body
    assert reverse(ACCEPT_URL, kwargs={"signed_token": signed_token}) in email.body


def test_no_email_sent_when_email_disabled(monkeypatch, pi_client, project):
    # views.EMAIL_ENABLED is read at import time, like in ColdFront's own
    # views; patch the module constant for this test.
    monkeypatch.setattr("coldfront_plugin_userinvite.views.EMAIL_ENABLED", False)
    post_invite(pi_client, project)
    assert len(mail.outbox) == 0
    # The invitation is still created; the link can be shared elsewhere.
    assert Invitation.objects.filter(project=project).exists()


def test_multiple_emails_in_one_submission(pi_client, project):
    response = post_invite(
        pi_client,
        project,
        emails="a@example.org, b@example.org\nc@example.org",
    )
    assert response.status_code == 200
    assert Invitation.objects.filter(project=project).count() == 3
    assert len(mail.outbox) == 3


def test_skips_already_pending_and_existing_members(pi_client, project, manager_user):
    create_invitation(project, email="pending@example.org")

    response = post_invite(
        pi_client,
        project,
        emails="pending@example.org, manager@example.org, new@example.org",
    )
    assert response.status_code == 200

    # Only the new address got an invitation.
    assert Invitation.objects.filter(project=project).count() == 2
    html = response.content.decode()
    assert "Skipped: pending@example.org (invite already pending)" in html
    assert "manager@example.org (already in project)" in html
    assert "Sent 1 invitation(s)." in html


def test_invalid_email_rerenders_form_with_errors(pi_client, project):
    response = post_invite(pi_client, project, emails="not-an-email")
    assert response.status_code == 200
    assert "Invalid email address(es): not-an-email" in response.content.decode()
    assert not Invitation.objects.filter(project=project).exists()


# ── Accepting invitations ───────────────────────────────────────────────────


def test_authenticated_user_accepts_invitation(client, project):
    invitation = create_invitation(project)
    user = get_user_model().objects.create_user(
        username="invitee",
        password="test-password",
        email="invitee@example.org",
    )
    client.force_login(user)

    # Accepting must go through Project.add_user, so the
    # project_activate_user signal fires for the new member
    # (downstream integrations hang off it).
    fired = []

    def receiver(sender, **kwargs):
        fired.append(kwargs.get("project_user_pk"))

    project_activate_user.connect(receiver)

    response = client.get(
        reverse(ACCEPT_URL, kwargs={"signed_token": invitation.get_signed_token()})
    )

    project_activate_user.disconnect(receiver)

    assert response.status_code == 302
    assert response.url == reverse("project-detail", kwargs={"pk": project.pk})

    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.ACCEPTED
    assert invitation.accepted_by == user
    assert invitation.accepted_at is not None

    project_user = ProjectUser.objects.get(user=user, project=project)
    assert project_user.role.name == "User"
    assert project_user.status.name == "Active"
    assert fired == [project_user.pk]


def test_unauthenticated_accept_redirects_to_login(client, project):
    invitation = create_invitation(project)
    signed_token = invitation.get_signed_token()

    response = client.get(reverse(ACCEPT_URL, kwargs={"signed_token": signed_token}))

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))
    assert "next=" in response.url
    # The token is kept in the session for the post-login redirect.
    assert client.session[AcceptInviteView.SESSION_KEY] == signed_token


def test_already_member_accept_updates_role(client, project):
    user = get_user_model().objects.create_user(
        username="member",
        password="test-password",
        email="member@example.org",
    )
    ProjectUser.objects.create(
        user=user,
        project=project,
        role=ProjectUserRoleChoice.objects.get(name="User"),
        status=ProjectUserStatusChoice.objects.get(name="Active"),
    )
    invitation = create_invitation(project, email="member@example.org", role="Manager")
    client.force_login(user)

    response = client.get(
        reverse(ACCEPT_URL, kwargs={"signed_token": invitation.get_signed_token()})
    )

    assert response.status_code == 302
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.REDUNDANT
    project_user = ProjectUser.objects.get(user=user, project=project)
    assert project_user.role.name == "Manager"


@override_settings(USERINVITE_LINK_EXPIRY_SECONDS=0)
def test_expired_link_is_rejected(client, project):
    invitation = create_invitation(project)
    user = get_user_model().objects.create_user(username="invitee")
    client.force_login(user)

    response = client.get(
        reverse(ACCEPT_URL, kwargs={"signed_token": invitation.get_signed_token()})
    )

    assert response.status_code == 302
    assert response.url == reverse("home")
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.PENDING


def test_invalid_link_is_rejected(client, project):
    user = get_user_model().objects.create_user(username="invitee")
    client.force_login(user)

    response = client.get(reverse(ACCEPT_URL, kwargs={"signed_token": "garbage-token"}))

    assert response.status_code == 302
    assert response.url == reverse("home")


def test_revoked_link_is_rejected(client, project):
    invitation = create_invitation(project)
    invitation.status = Invitation.Status.REVOKED
    invitation.save(update_fields=["status"])

    user = get_user_model().objects.create_user(username="invitee")
    client.force_login(user)

    response = client.get(
        reverse(ACCEPT_URL, kwargs={"signed_token": invitation.get_signed_token()})
    )

    assert response.status_code == 302
    assert response.url == reverse("home")
    assert not ProjectUser.objects.filter(project=project).exists()


# ── Revoke / resend / history ────────────────────────────────────────────────


def test_revoke_pending_invitation(pi_client, project):
    invitation = create_invitation(project)

    response = pi_client.post(
        reverse(
            "userinvite-revoke",
            kwargs={"pk": project.pk, "invite_pk": invitation.pk},
        )
    )

    assert response.status_code == 200
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.REVOKED
    assert f"Invitation to {invitation.email} revoked." in response.content.decode()


def test_resend_creates_fresh_invitation(pi_client, project):
    old_invitation = create_invitation(project)
    old_token = old_invitation.token

    response = pi_client.post(
        reverse(
            "userinvite-resend",
            kwargs={"pk": project.pk, "invite_pk": old_invitation.pk},
        )
    )

    assert response.status_code == 200
    old_invitation.refresh_from_db()
    assert old_invitation.status == Invitation.Status.REVOKED

    new_invitation = Invitation.objects.get(
        project=project, status=Invitation.Status.PENDING
    )
    assert new_invitation.token != old_token
    assert len(mail.outbox) == 1
    assert "New invitation sent to invitee@example.org." in response.content.decode()


def test_list_shows_history_on_request(pi_client, project):
    revoked = create_invitation(project, email="revoked@example.org")
    revoked.status = Invitation.Status.REVOKED
    revoked.save(update_fields=["status"])
    create_invitation(project, email="pending@example.org")

    default_view = pi_client.get(
        reverse(LIST_URL, kwargs={"pk": project.pk})
    ).content.decode()
    assert "pending@example.org" in default_view
    assert "revoked@example.org" not in default_view

    history_view = pi_client.get(
        reverse(LIST_URL, kwargs={"pk": project.pk}), {"show_all": "1"}
    ).content.decode()
    assert "pending@example.org" in history_view
    assert "revoked@example.org" in history_view


def test_stale_invitations_expire_lazily(pi_client, project):
    invitation = create_invitation(project, email="stale@example.org")
    Invitation.objects.filter(pk=invitation.pk).update(
        created=timezone.now() - timezone.timedelta(days=8)
    )

    response = pi_client.get(reverse(LIST_URL, kwargs={"pk": project.pk}))

    assert response.status_code == 200
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.EXPIRED


# ── Add-users page integration ──────────────────────────────────────────────


def test_add_users_page_shows_invite_section(pi_client, project):
    response = pi_client.get(
        reverse("project-add-users-search", kwargs={"pk": project.pk})
    )

    assert response.status_code == 200
    assert "Invite Users by Email" in response.content.decode()
    assert set(response.context["invite_form"].fields) == {"emails", "role"}


def test_add_users_page_shows_default_user_search_by_default(pi_client, project):
    response = pi_client.get(
        reverse("project-add-users-search", kwargs={"pk": project.pk})
    )

    html = response.content.decode()
    assert 'id="post-form"' in html
    assert 'id="id_q"' in html


@override_settings(USERINVITE_DISABLE_USER_SEARCH=True)
def test_disabled_user_search_hides_search_but_keeps_invite_section(pi_client, project):
    response = pi_client.get(
        reverse("project-add-users-search", kwargs={"pk": project.pk})
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert "Invite Users by Email" in html
    assert "Add users to project: Test Project" in html
    assert 'id="post-form"' not in html
    assert 'id="id_q"' not in html
    assert 'id="search_results"' not in html


@override_settings(USERINVITE_DISABLE_USER_SEARCH=True)
def test_disabled_user_search_blocks_search_results_endpoint(pi_client, project):
    response = pi_client.post(
        reverse("project-add-users-search-results", kwargs={"pk": project.pk}),
        {"q": "someone", "search_by": "username"},
    )

    assert response.status_code == 404


@override_settings(USERINVITE_DISABLE_USER_SEARCH=True)
def test_disabled_user_search_blocks_add_users_endpoint(pi_client, project):
    response = pi_client.post(
        reverse("project-add-users", kwargs={"pk": project.pk}),
        {},
    )

    assert response.status_code == 404
    assert (
        not ProjectUser.objects.filter(project=project)
        .exclude(user=project.pi)
        .exists()
    )
