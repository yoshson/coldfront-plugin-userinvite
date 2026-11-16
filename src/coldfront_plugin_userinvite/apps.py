"""Application configuration for the userinvite plugin."""

import logging

from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class UserinviteConfig(AppConfig):
    """Configure the plugin and attach it to ColdFront's add-users page."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "coldfront_plugin_userinvite"
    label = "userinvite"
    verbose_name = "User Invites"

    def ready(self):
        from django.conf import settings

        # The automatic integration can be disabled, e.g. to wire the
        # invite section up manually or to expose the views behind a
        # custom URLconf.
        if not getattr(settings, "USERINVITE_PATCH_ADD_USERS_VIEW", True):
            logger.info(
                "Userinvite plugin: ColdFront integration (add-users view "
                "and URLs) disabled via USERINVITE_PATCH_ADD_USERS_VIEW."
            )
            return

        try:
            from .patch import apply_patches

            apply_patches()
        except ImportError as exc:  # pragma: no cover - defensive
            raise ImproperlyConfigured(
                "coldfront_plugin_userinvite requires ColdFront to be "
                "installed and is meant to be used inside a ColdFront "
                "deployment. If you do not want the add-users view to be "
                "patched, set USERINVITE_PATCH_ADD_USERS_VIEW = False in "
                "your ColdFront settings."
            ) from exc
