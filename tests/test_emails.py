"""Unit tests for the invite form's email parsing.

``parse_emails`` needs no configured Django settings, so these run with
the plain dev dependency group (no ColdFront install required).
"""

import pytest
from django.core.exceptions import ValidationError

from coldfront_plugin_userinvite.emails import parse_emails


def test_split_by_newlines_commas_and_semicolons():
    assert parse_emails("a@b.de, c@d.de; e@f.de\ng@h.de") == [
        "a@b.de",
        "c@d.de",
        "e@f.de",
        "g@h.de",
    ]


def test_empty_parts_and_whitespace_are_ignored():
    assert parse_emails("  a@b.de ,\n,,  \nc@d.de ") == ["a@b.de", "c@d.de"]


def test_addresses_are_lowercased_and_deduplicated_in_order():
    assert parse_emails("A@B.de, c@d.de, a@b.de, C@D.de") == [
        "a@b.de",
        "c@d.de",
    ]


def test_invalid_addresses_raise_listing_them():
    with pytest.raises(ValidationError, match="not-an-email"):
        parse_emails("a@b.de, not-an-email")


def test_all_invalid_input_lists_every_error():
    with pytest.raises(ValidationError) as excinfo:
        parse_emails("foo, bar")
    assert "foo" in str(excinfo.value)
    assert "bar" in str(excinfo.value)


def test_input_without_any_address_raises():
    with pytest.raises(ValidationError, match="at least one"):
        parse_emails("  \n ,")
