"""Django settings for a basic ColdFront test instance with this plugin.

Assembled from ColdFront's own config fragments (the same ones a production
deployment composes via ``coldfront.config.settings``), so the integration
tests run against the real URLconf, templates, middleware and views of a
ColdFront 1.1.x deployment — plus ``coldfront_plugin_userinvite``.

Only deviations from a stock ColdFront instance:
- an in-memory SQLite database (created and migrated by pytest-django),
- a deterministic SECRET_KEY (never used for anything security-relevant),
- the in-memory email backend (nothing should leave the test run),
- email sending enabled so the invite flow is exercised for real.
"""

# coldfront.config.urls accesses split_settings.tools without importing the
# submodule itself; import it here so the urlconf loads outside of a full
# coldfront.config.settings bootstrap.
import split_settings.tools  # noqa: F401
from coldfront.config.auth import *  # noqa: F403 - backends, login URLs
from coldfront.config.base import *  # noqa: F403 - apps, middleware, templates
from coldfront.config.core import *  # noqa: F403 - center/allocation settings
from coldfront.config.email import *  # noqa: F403 - email settings
from coldfront.config.env import ENV
from coldfront.config.logging import *  # noqa: F403 - message tags, logging

SECRET_KEY = "userinvite-integration-tests-only"
DEBUG = True

# In-memory SQLite for the test run; override DB_URL (e.g. with
# manage.py migrate) to inspect the instance in a file database.
DATABASES = {
    "default": ENV.db_url(var="DB_URL", default="sqlite://:memory:"),
}

# Nothing should leave the test run, even if a code path sends mail.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# The invite flow sends its emails through ColdFront's send_email_template.
EMAIL_ENABLED = True
EMAIL_SENDER = "coldfront-test@example.org"

# The test instance ships no built frontend assets. Development mode makes
# django-vite render dev-server URLs instead of reading a build manifest
# (whose absence would otherwise surface as a system-check warning).
DJANGO_VITE = {
    "default": {
        "dev_mode": True,
    }
}

# Prepend (not append) so the plugin's project/project_add_users.html
# template override takes precedence over coldfront.core.project's —
# the app template loader searches INSTALLED_APPS in order. This mirrors
# what a production deployment has to do (see README).
INSTALLED_APPS = [
    "coldfront_plugin_userinvite",
    *INSTALLED_APPS,  # noqa: F405 - from coldfront.config.base
]
