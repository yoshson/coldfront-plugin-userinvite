# coldfront-plugin-userinvite

A [ColdFront](https://coldfront.readthedocs.io/) plugin that lets PIs and
project managers **invite users to join a project by email** — users who
do not yet have a role in the project. The invited user receives an email
with a **signed, timestamped, one-time link**; clicking it while logged in
adds them to the project with the chosen role.

The plugin manages **project membership only**. It does not create ColdFront
accounts: the invitee must already have one (or obtain one through the
deployment's normal registration/IdP flow), because accepting the link relies
on ColdFront's regular login.

## How it works

The plugin adds an *Invite Users by Email* section to ColdFront's
*add users to project* page (`project/<pk>/add-users-search/`):

- The invite form accepts **multiple email addresses** (one per line or
  comma/semicolon-separated) plus the **project role** the invitees will
  receive.
- For every address that passes these checks, an `Invitation` record is
  created and an email with the one-time accept link is sent through
  ColdFront's own `send_email_template` machinery. Addresses that are
  already active project members or already have a pending invitation
  are skipped and reported back.
- The section also lists the project's **pending invitations** with
  actions to **revoke** or **resend** them, plus a *show history* toggle
  covering accepted/expired/revoked/redundant invitations. All actions
  run via [htmx](https://htmx.org/) and swap HTML fragments — no full
  page reloads.

### Permissions

Sending, revoking and resending invitations requires the user to be the
project PI, an active project Manager, or a superuser. Accepting an
invitation only requires a logged-in ColdFront account.

### The accept link

The link contains a random token generated for the invitation, signed and
timestamped with Django's `TimestampSigner` (using `SECRET_KEY`).
Accepting verifies the signature and age, loads a still-pending invitation,
and applies that invitation's stored project and role:

- The signature expires after `USERINVITE_LINK_EXPIRY_SECONDS`
  (default: 7 days). An expired link is rejected with an error message.
- The link only works while the invitation is **pending**: revoking (or
  resending, which revokes and re-creates) invalidates it immediately.
- Anonymous visitors are redirected to the login page with a `next` URL
  pointing back at the same signed link, so the flow continues after
  login.
- A logged-in invitee is added to the project as an *Active* user with
  the invited role — through `Project.add_user`, so the
  `project_activate_user` signal fires and downstream integrations
  (e.g. allocation membership sync, PI/manager notifications) see the
  new member. If they are already an active member, the invitation is
  marked **redundant** and their role is updated to the invited one
  (unless they are the PI).

### Security note

The signed link is a **bearer credential**: acceptance does not compare
the logged-in account's email address with the invitation's email address.
Whoever holds the link and logs in can claim the invitation. Treat
invitation emails as sensitive, and revoke an invitation to invalidate a
leaked link.

Invitation statuses: `pending` → `accepted` / `redundant`, or
`expired` / `revoked`. Pending invitations past their expiry are marked
`expired` lazily whenever the add-users page or invitation list is
rendered, and a Django-Q task
(`coldfront_plugin_userinvite.tasks.expire_stale_invitations`) does the
same for all projects; register it with the
`add_userinvite_scheduled_tasks` management command (see below).

## Installation

The plugin requires Python 3.12+, Django 5.2+ and a working ColdFront 1.1.x
deployment. It is not published on PyPI (yet); install it directly from the
[GitHub repository](https://github.com/yoshson/coldfront-plugin-userinvite)
inside your ColdFront environment:

```console
$ uv pip install git+https://github.com/yoshson/coldfront-plugin-userinvite.git
```

Enable the plugin by creating `coldfront/config/plugins/userinvite.py`
in your ColdFront installation:

```python
from coldfront.config.base import INSTALLED_APPS

# Prepend (not append!) so the plugin's project/project_add_users.html
# template override takes precedence over coldfront.core.project's —
# the app template loader searches INSTALLED_APPS in order.
INSTALLED_APPS = [
    'coldfront_plugin_userinvite',
    *INSTALLED_APPS,
]
```

and register it in `coldfront/config/settings.py`:

```python
plugin_configs['PLUGIN_USERINVITE'] = 'plugins/userinvite.py'
```

Then set `PLUGIN_USERINVITE=True` in your environment (or local
settings) and run migrations:

```console
$ coldfront migrate
```

The plugin hooks into the add-users page and registers its URLs at
application startup — no further wiring is required. To have expired
invitations swept up daily, register the Django-Q task once:

```console
$ coldfront add_userinvite_scheduled_tasks
```

(There is also a plain `coldfront expire_stale_invitations` command for
manual or cron-style sweeps.)

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `USERINVITE_LINK_EXPIRY_SECONDS` | `604800` | Lifetime of the signed accept link (and of a pending invitation), in seconds. |
| `USERINVITE_DISABLE_USER_SEARCH` | `False` | Hide ColdFront's default user-search from the *add users* page and disable the endpoints behind it (`add-users-search-results/` and `add-users/`), so ColdFront's add-users page only offers email invitations. |
| `USERINVITE_PATCH_COLDFRONT` | `True` | Automatically integrate with ColdFront: extend `ProjectAddUsersSearchView` with the invite section, guard the default user-search endpoints, and append the plugin's URLs to `coldfront.config.urls`. Set to `False` if you want to wire things up yourself — e.g. mix `coldfront_plugin_userinvite.views.InviteUsersMixin` into a custom view and include `coldfront_plugin_userinvite.urls` in your own URLconf (or ColdFront's `local_urls.py` hook). |

`USERINVITE_PATCH_ADD_USERS_VIEW` is the deprecated former name of
`USERINVITE_PATCH_COLDFRONT`; it is still honored when the new setting is
unset.

`USERINVITE_DISABLE_USER_SEARCH` is applied by the automatic integration;
it has no effect when `USERINVITE_PATCH_COLDFRONT` is `False` (a manual
wiring can render its own template instead).

Emails are only sent when ColdFront's own `EMAIL_ENABLED` setting is
`True` and `EMAIL_SENDER` is configured. When email is disabled the
invitation is still created, but the signed link is only available through
the invitation record (there is no copy-link UI). The email template ships
with the plugin and can be overridden per deployment at
`userinvite/email/invite_email.txt`.

## Django admin

The plugin adds an *Invitations* admin section listing every invitation
with its project, role, status and acceptance (who accepted, when),
filterable by status/project/role and searchable by email and project
title. Tokens are read-only.

## Internals

ColdFront 1.1.x has no extension point for adding sections to its views,
and no plugin URL registration hook. At application startup
(`AppConfig.ready()`), the plugin therefore:

1. wraps `coldfront.core.project.views.ProjectAddUsersSearchView.
   get_context_data` to add the invite form and the pending invitations
   to the template context (and, when `USERINVITE_DISABLE_USER_SEARCH` is
   enabled, to drop the default search form and set a template flag);
2. guards `ProjectAddUsersSearchResultsView.post` and
   `ProjectAddUsersView.post` to return 404 while that setting is
   enabled, so the default search/add-existing-user flow cannot be used;
3. appends `path(settings.BASE_PATH, include(
   "coldfront_plugin_userinvite.urls"))` to `coldfront.config.urls`'s
   `urlpatterns`, so the invite endpoints (`userinvite-*`) and the
   public accept link resolve.

The *Invite Users by Email* section is rendered by the plugin's template
override `project/project_add_users.html`, which extends ColdFront's own
template. Normally it appends the section after ColdFront's content; with
`USERINVITE_DISABLE_USER_SEARCH` enabled it renders the heading and the
invite section instead. This is why the app must be **prepended** to
`INSTALLED_APPS`. The root URLconf is resolved lazily — on the first
request or `reverse()` call, i.e. after `ready()` has run — so the
appended patterns are picked up everywhere. Deployments with a custom
`ROOT_URLCONF` can disable the automatic integration and include the URLs
themselves. All patching lives in
`coldfront_plugin_userinvite/patch.py` and is the only module that needs
adapting if ColdFront's internals change.

## Development

```console
$ uv sync
$ uv run pytest
$ uv run ruff check
$ uv run ruff format --check
```

The email parsing is free of Django settings and covered by unit tests.

### Integration tests

The Django integration is exercised against a **basic ColdFront test
instance** booted in-process: `tests/integration/settings.py` assembles the
settings from ColdFront's own config fragments, pytest-django creates and
migrates an in-memory SQLite database, and the tests drive the real
add-users page, invite endpoints and accept links with logged-in users.
Emails go to the in-memory backend and are asserted on directly. Run
them with the `integration` dependency group, which installs
ColdFront 1.1.x:

```console
$ uv sync --group integration
$ uv run pytest tests/integration
```

Without the group, plain `uv run pytest` skips `tests/integration` at
collection time and runs only the email parsing unit tests.

The repo root contains a minimal `manage.py` pointing at the test instance
settings (pytest-django needs it to locate the project). It also allows
exploring the instance by hand:

```console
$ uv run --group integration python manage.py check
$ DB_URL=sqlite:///coldfront.db uv run --group integration python manage.py migrate
```
