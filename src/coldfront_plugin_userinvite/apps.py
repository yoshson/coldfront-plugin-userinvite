"""Application configuration for the userinvite plugin."""

import logging

from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


def _integration_enabled():
    """Whether the automatic ColdFront integration should be applied.

    ``USERINVITE_PATCH_COLDFRONT`` is the current name; the former
    ``USERINVITE_PATCH_ADD_USERS_VIEW`` is still honored when the new
    setting is unset.
    """
    from django.conf import settings

    if hasattr(settings, "USERINVITE_PATCH_COLDFRONT"):
        return settings.USERINVITE_PATCH_COLDFRONT
    return getattr(settings, "USERINVITE_PATCH_ADD_USERS_VIEW", True)


class UserinviteConfig(AppConfig):
    """Configure the plugin and apply the automatic ColdFront integration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "coldfront_plugin_userinvite"
    label = "userinvite"
    verbose_name = "User Invites"

    def ready(self):
        # The automatic integration can be disabled, e.g. to wire the
        # invite section up manually or to expose the views behind a
        # custom URLconf.
        if not _integration_enabled():
            logger.info(
                "Userinvite plugin: automatic ColdFront integration "
                "(add-users view, user-search guard and URLs) disabled via "
                "USERINVITE_PATCH_COLDFRONT."
            )
            return

        try:
            from .patch import apply_patches

            apply_patches()
        except ImportError as exc:  # pragma: no cover - defensive
            raise ImproperlyConfigured(
                "coldfront_plugin_userinvite requires ColdFront to be "
                "installed and is meant to be used inside a ColdFront "
                "deployment. If you do not want the automatic integration, "
                "set USERINVITE_PATCH_COLDFRONT = False in your ColdFront "
                "settings."
            ) from exc
