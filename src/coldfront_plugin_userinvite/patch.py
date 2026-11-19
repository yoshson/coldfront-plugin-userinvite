"""Glue between this plugin and ColdFront's add-users flow.

ColdFront (as of 1.1.x) offers no extension point for adding sections to
the "add users to project" page, and plugins have no way to register URL
patterns. The plugin therefore patches ColdFront in three places at
application startup:

- ``ProjectAddUsersSearchView.get_context_data`` is wrapped to add the
  invite form and the pending invitations to the template context (the
  section itself is rendered by the plugin's ``project_add_users.html``
  template override), and to hide the default user-search when
  ``USERINVITE_DISABLE_USER_SEARCH`` is enabled;
- ``ProjectAddUsersSearchResultsView.post`` and ``ProjectAddUsersView.post``
  are guarded to return 404 while that setting is enabled, so the default
  search/add-existing-user flow is disabled as a whole;
- the plugin's URL patterns are appended to ``coldfront.config.urls`` so
  the invite form's htmx endpoints and the public accept link resolve
  where the templates reverse them (``userinvite-*``).

If ColdFront's internals change in an incompatible way, this is the only
module that needs to be adapted.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _user_search_disabled():
    """Whether the default ColdFront user-search flow is disabled.

    Read at request time (not at startup) so the setting can be toggled
    with ``override_settings``/without reloading the process.
    """
    return getattr(settings, "USERINVITE_DISABLE_USER_SEARCH", False)


def apply_patches():
    """Add the invite section, guard the user-search flow and register
    the plugin's URLs.

    Idempotent: calling it multiple times (e.g. during tests) is safe.
    """
    _patch_add_users_view()
    _patch_user_search_views()
    _patch_urlconf()


def _patch_add_users_view():
    """Wrap the add-users search view to provide the invite context.

    When ``USERINVITE_DISABLE_USER_SEARCH`` is enabled, the default search
    form is also dropped from the context and the template flag is set.
    """
    from coldfront.core.project import views as project_views

    from .views import invite_context

    view = project_views.ProjectAddUsersSearchView
    if getattr(view, "_userinvite_patched", False):
        return

    original_get_context_data = view.get_context_data

    def get_context_data(self, *args, **kwargs):
        context = original_get_context_data(self, *args, **kwargs)
        project = context.get("project")
        if project is not None:
            context.update(invite_context(project))
        if _user_search_disabled():
            # The plugin's project_add_users.html uses this flag to skip
            # ColdFront's content block; the form is dropped as well so
            # nothing can fall back to rendering it.
            context.pop("user_search_form", None)
            context["userinvite_user_search_disabled"] = True
        return context

    view.get_context_data = get_context_data
    # Kept for tests and manual un-patching (see test_boot.py).
    view._userinvite_original_get_context_data = original_get_context_data
    view._userinvite_patched = True
    logger.info(
        "Userinvite plugin: patched "
        "coldfront.core.project.views.ProjectAddUsersSearchView to add "
        "the invite section to the add-users page."
    )


def _patch_user_search_views():
    """Guard ColdFront's search/add-existing-user endpoints.

    The search UI is hidden by the template, but the endpoints could
    still be reached directly (or via a stale page). They return 404 when
    ``USERINVITE_DISABLE_USER_SEARCH`` is enabled, so the default flow is
    disabled as a whole. The guard is always installed and checks the
    setting per request; it is inert when the setting is off.
    """
    from coldfront.core.project import views as project_views
    from django.http import HttpResponseNotFound

    view_names = (
        "ProjectAddUsersSearchResultsView",
        "ProjectAddUsersView",
    )
    for view_name in view_names:
        view = getattr(project_views, view_name)
        if getattr(view, "_userinvite_user_search_patched", False):
            continue

        original_post = view.post

        def post(self, request, *args, __original=original_post, **kwargs):
            if _user_search_disabled():
                return HttpResponseNotFound("User search is disabled.")
            return __original(self, request, *args, **kwargs)

        view.post = post
        view._userinvite_original_post = original_post
        view._userinvite_user_search_patched = True

    logger.info(
        "Userinvite plugin: guarded ColdFront's user-search endpoints "
        "(disabled when USERINVITE_DISABLE_USER_SEARCH is enabled)."
    )


def _patch_urlconf():
    """Append the plugin's URL patterns to ColdFront's root URLconf.

    ColdFront has no plugin URL registration mechanism. The root URLconf
    (``coldfront.config.urls``) is resolved lazily — on the first request
    or ``reverse()`` call, i.e. after ``AppConfig.ready()`` has run — so
    appending here is picked up everywhere. Deployments with a custom
    ``ROOT_URLCONF`` can set ``USERINVITE_PATCH_ADD_USERS_VIEW = False``
    and include ``coldfront_plugin_userinvite.urls`` themselves (e.g. via
    ColdFront's ``local_urls.py`` hook).
    """
    import coldfront.config.urls as coldfront_urls
    from django.conf import settings
    from django.urls import include, path

    from . import urls as plugin_urls

    if getattr(coldfront_urls, "_userinvite_urls_included", False):
        return

    coldfront_urls.urlpatterns.append(
        path(getattr(settings, "BASE_PATH", ""), include(plugin_urls))
    )
    coldfront_urls._userinvite_urls_included = True
    logger.info(
        "Userinvite plugin: appended coldfront_plugin_userinvite URLs to "
        "coldfront.config.urls."
    )
