"""Glue between this plugin and ColdFront's add-users flow.

ColdFront (as of 1.1.x) offers no extension point for adding sections to
the "add users to project" page, and plugins have no way to register URL
patterns. The plugin therefore patches two things at application startup:

- ``ProjectAddUsersSearchView.get_context_data`` is wrapped to add the
  invite form and the pending invitations to the template context (the
  section itself is rendered by the plugin's ``project_add_users.html``
  template override), and
- the plugin's URL patterns are appended to ``coldfront.config.urls`` so
  the invite form's htmx endpoints and the public accept link resolve
  where the templates reverse them (``userinvite-*``).

If ColdFront's internals change in an incompatible way, this is the only
module that needs to be adapted.
"""

import logging

logger = logging.getLogger(__name__)


def apply_patches():
    """Add the invite section to ColdFront's add-users page and register
    the plugin's URLs.

    Idempotent: calling it multiple times (e.g. during tests) is safe.
    """
    _patch_add_users_view()
    _patch_urlconf()


def _patch_add_users_view():
    """Wrap the add-users search view to provide the invite context."""
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
