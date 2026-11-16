"""Parsing of the invite form's email address input.

Kept in its own module (with no dependency on configured Django settings)
so it can be covered by plain unit tests; Django's ``validate_email``
works without a configured settings module.
"""

import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

# Addresses may be separated by newlines, commas or semicolons.
EMAIL_SPLIT_RE = re.compile(r"[,;\n]+")


def parse_emails(raw):
    """Split the invite form input into a list of valid, deduplicated
    email addresses (lowercased, input order preserved).

    Raises ValidationError listing the invalid addresses, or when the
    input contains no address at all.
    """
    emails = []
    errors = []
    for part in EMAIL_SPLIT_RE.split(raw):
        email = part.strip().lower()
        if not email:
            continue
        try:
            validate_email(email)
            emails.append(email)
        except ValidationError:
            errors.append(email)
    if errors:
        raise ValidationError(f"Invalid email address(es): {', '.join(errors)}")
    if not emails:
        raise ValidationError("Please enter at least one email address.")
    # Deduplicate while preserving the input order.
    return list(dict.fromkeys(emails))
