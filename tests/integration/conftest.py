"""Fixtures for the ColdFront integration tests.

The database is created and migrated by pytest-django (which also runs the
plugin's initial migration on a fresh database). A session fixture then
rounds it off into a *basic ColdFront instance*: ColdFront's status choices
(``ProjectStatusChoice`` etc.) are not created by migrations but by its
``add_default_project_choices`` command, and the project model's
``field_of_science`` default row normally comes with the NSF import data.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command


@pytest.fixture(scope="session", autouse=True)
def coldfront_test_instance(django_db_setup, django_db_blocker):
    """Set up the basic ColdFront test instance once per test session."""
    with django_db_blocker.unblock():
        call_command("add_default_project_choices")
        # Project.field_of_science defaults to FieldOfScience.DEFAULT_PK;
        # create that single row so test projects can be created without
        # the full NSF field-of-science import.
        from coldfront.core.field_of_science.models import FieldOfScience

        FieldOfScience.objects.get_or_create(
            pk=FieldOfScience.DEFAULT_PK,
            defaults={"description": "Other"},
        )


@pytest.fixture
def pi_user(db):
    """A user who may create projects (ColdFront checks userprofile.is_pi)."""
    user = get_user_model().objects.create_user(
        username="test-pi", password="test-password"
    )
    user.userprofile.is_pi = True
    user.userprofile.save()
    return user


@pytest.fixture
def pi_client(client, pi_user):
    """A Django test client logged in as the PI."""
    client.force_login(pi_user)
    return client


@pytest.fixture
def project(db, pi_user):
    """An active project owned by the PI."""
    from coldfront.core.project.models import Project, ProjectStatusChoice

    return Project.objects.create(
        title="Test Project",
        pi=pi_user,
        status=ProjectStatusChoice.objects.get(name="Active"),
    )


@pytest.fixture
def manager_user(db, project):
    """A user who is an active Manager on the project."""
    from coldfront.core.project.models import (
        ProjectUser,
        ProjectUserRoleChoice,
        ProjectUserStatusChoice,
    )

    user = get_user_model().objects.create_user(
        username="test-manager",
        password="test-password",
        email="manager@example.org",
    )
    ProjectUser.objects.create(
        user=user,
        project=project,
        role=ProjectUserRoleChoice.objects.get(name="Manager"),
        status=ProjectUserStatusChoice.objects.get(name="Active"),
    )
    return user


@pytest.fixture
def manager_client(client, manager_user):
    """A Django test client logged in as the project Manager."""
    client.force_login(manager_user)
    return client


@pytest.fixture
def outsider_client(client, db):
    """A client logged in as a user with no relation to the project."""
    user = get_user_model().objects.create_user(
        username="test-outsider", password="test-password"
    )
    client.force_login(user)
    return client
