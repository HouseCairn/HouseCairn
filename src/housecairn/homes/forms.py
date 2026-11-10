"""Forms of the home and household screens. Validation only; rules live in `services`."""

from typing import Any

from django import forms
from django.contrib.auth import password_validation
from django.utils.translation import gettext_lazy as _

from housecairn.homes.models import Hemisphere, Home, Role
from housecairn.homes.sso import Provider


class HomeForm(forms.ModelForm[Home]):
    class Meta:
        model = Home
        fields = ["name", "currency", "hemisphere"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["hemisphere"].required = False

    def clean_hemisphere(self) -> str:
        """Left out, the hemisphere is the default one (a form posted by an older client)."""
        return str(
            self.cleaned_data.get("hemisphere") or self.instance.hemisphere or Hemisphere.NORTH
        )


class InviteForm(forms.Form):
    email = forms.EmailField(label=_("Email address"), max_length=254)
    role = forms.ChoiceField(label=_("Role"), choices=Role.choices, initial=Role.MEMBER)


class RoleForm(forms.Form):
    role = forms.ChoiceField(label=_("Role"), choices=Role.choices)


class ProviderForm(forms.Form):
    provider = forms.ChoiceField(label=_("Sign-in required to open this home"), required=False)

    def __init__(self, *args: Any, providers: list[Provider], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        choices: list[tuple[str, str]] = [("", str(_("No requirement")))]
        choices += [(p.id, p.name) for p in providers]
        field = self.fields["provider"]
        assert isinstance(field, forms.ChoiceField)  # noqa: S101 - narrows the type
        field.choices = choices


class InvitationSignupForm(forms.Form):
    """Password of the account created by accepting an invitation."""

    # Shown, not editable: the account takes the invited address.
    email = forms.EmailField(
        label=_("Email address"),
        disabled=True,
        required=False,
        widget=forms.EmailInput(attrs={"autocomplete": "username"}),
    )
    password1 = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label=_("Password (again)"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args: Any, email: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["email"].initial = email

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        first, second = data.get("password1"), data.get("password2")
        if first and second and first != second:
            raise forms.ValidationError(_("The two passwords differ."))
        if first:
            password_validation.validate_password(first)
        return data


class DeleteHomeForm(forms.Form):
    confirmation = forms.CharField(
        label=_("Type the name of the home to confirm"), max_length=120, strip=True
    )


class ImportForm(forms.Form):
    """CSV tables to import into a home, one optional file per table (docs/adr/0048).

    The confirmation posts the text of the files back, as checked by the preview.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        from housecairn.homes import csv_import

        super().__init__(*args, **kwargs)
        for name, entity in csv_import.entities().items():
            self.fields[name] = forms.FileField(
                label=entity.label,
                required=False,
                widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
            )
            self.fields[f"text_{name}"] = forms.CharField(
                required=False, strip=False, widget=forms.HiddenInput
            )

    def texts(self) -> dict[str, str]:
        """The text of each table given: an upload, or the text sent back by the preview."""
        from housecairn.homes import csv_import

        uploads = {
            name: self.cleaned_data[name]
            for name in csv_import.entities()
            if self.cleaned_data.get(name)
        }
        if uploads:
            return csv_import.texts_from_uploads(uploads)
        texts = {
            name: self.cleaned_data[f"text_{name}"]
            for name in csv_import.entities()
            if self.cleaned_data.get(f"text_{name}")
        }
        if sum(len(t.encode()) for t in texts.values()) > csv_import.MAX_BYTES:
            raise csv_import.ImportRefusedError(csv_import.too_large_message())
        return texts


class RestoreForm(forms.Form):
    """The archive of a home, made by Export all data (docs/adr/0048)."""

    archive = forms.FileField(
        label=_("Archive of a home"),
        help_text=_("The zip file that Export all data gave, as it is."),
    )
