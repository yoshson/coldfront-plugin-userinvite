from coldfront.core.project.models import ProjectUserRoleChoice
from django import forms

from coldfront_plugin_userinvite.emails import parse_emails


class InviteUsersForm(forms.Form):
    """Accepts multiple emails (one per line or comma-separated) plus the
    project role the invited users will receive on accepting."""

    emails = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Enter email addresses, one per line or comma-separated",
            }
        ),
        label="Email addresses",
    )
    role = forms.ModelChoiceField(
        queryset=ProjectUserRoleChoice.objects.all(),
        label="Role",
        initial=lambda: ProjectUserRoleChoice.objects.get(name="User"),
    )

    def clean_emails(self):
        return parse_emails(self.cleaned_data["emails"])
