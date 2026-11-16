from django.urls import path

from coldfront_plugin_userinvite import views

urlpatterns = [
    path(
        "invite/accept/<path:signed_token>/",
        views.AcceptInviteView.as_view(),
        name="userinvite-accept",
    ),
    path(
        "project/<int:pk>/invite/send/",
        views.InviteUsersView.as_view(),
        name="userinvite-send",
    ),
    path(
        "project/<int:pk>/invite/list/",
        views.InviteListView.as_view(),
        name="userinvite-list",
    ),
    path(
        "project/<int:pk>/invite/<int:invite_pk>/revoke/",
        views.RevokeInviteView.as_view(),
        name="userinvite-revoke",
    ),
    path(
        "project/<int:pk>/invite/<int:invite_pk>/resend/",
        views.ResendInviteView.as_view(),
        name="userinvite-resend",
    ),
]
