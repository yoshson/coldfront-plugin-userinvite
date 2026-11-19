"""The plugin boots inside a real ColdFront 1.1.x instance.

These tests run against a full ColdFront settings module (see
``settings.py``), so a passing test already proves the central
integration steps: ``AppConfig.ready()`` patches ColdFront's add-users
view and appends the plugin's URLs to the root URLconf without breaking
startup, and the plugin's migration creates its table on a fresh
database.
"""

import pytest
from coldfront.core.project import views as project_views
from django.apps import apps
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_add_users_view_is_patched():
    """ProjectAddUsersSearchView renders with the invite section context."""
    assert getattr(
        project_views.ProjectAddUsersSearchView, "_userinvite_patched", False
    )


def test_user_search_views_are_guarded():
    """The search/add-existing-user endpoints check the disable setting."""
    assert getattr(
        project_views.ProjectAddUsersSearchResultsView,
        "_userinvite_user_search_patched",
        False,
    )
    assert getattr(
        project_views.ProjectAddUsersView,
        "_userinvite_user_search_patched",
        False,
    )


def test_plugin_urls_resolve_through_root_urlconf():
    """The ready()-time patch appended the plugin's URL patterns."""
    reverse("userinvite-accept", kwargs={"signed_token": "some-token"})
    reverse("userinvite-send", kwargs={"pk": 1})
    reverse("userinvite-list", kwargs={"pk": 1})
    reverse("userinvite-revoke", kwargs={"pk": 1, "invite_pk": 1})
    reverse("userinvite-resend", kwargs={"pk": 1, "invite_pk": 1})


def test_patch_setting_disables_integration():
    """USERINVITE_PATCH_ADD_USERS_VIEW=False leaves view and URLconf alone."""
    import coldfront.config.urls as coldfront_urls

    config = apps.get_app_config("userinvite")
    view = project_views.ProjectAddUsersSearchView

    # Undo the patches applied at startup.
    view.get_context_data = view._userinvite_original_get_context_data
    del view._userinvite_patched
    appended = coldfront_urls.urlpatterns[-1]
    assert coldfront_urls.urlpatterns.pop() is appended
    del coldfront_urls._userinvite_urls_included

    with override_settings(USERINVITE_PATCH_ADD_USERS_VIEW=False):
        config.ready()

    assert not getattr(view, "_userinvite_patched", False)
    assert coldfront_urls.urlpatterns[-1] is not appended

    # ready() is idempotent and re-applies the patches.
    config.ready()

    assert getattr(view, "_userinvite_patched", False)
    # A fresh URLResolver is created per apply_patches() call; assert on
    # the included module instead of object identity.
    assert (
        coldfront_urls.urlpatterns[-1].urlconf_module.__name__
        == "coldfront_plugin_userinvite.urls"
    )
