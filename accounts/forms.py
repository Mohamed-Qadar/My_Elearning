from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import InstructorApplication, User, normalize_phone


class RegisterForm(forms.ModelForm):
    """Email and phone are normalized and validated by User.clean()."""

    password1 = forms.CharField(label=_("Password"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Confirm password"), widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["email", "phone"]
        labels = {"email": _("Email address"), "phone": _("Phone number")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2:
            if password1 != password2:
                self.add_error("password2", _("The two passwords do not match."))
            else:
                user = User(email=cleaned_data.get("email"), phone=cleaned_data.get("phone"))
                try:
                    validate_password(password1, user)
                except ValidationError as error:
                    self.add_error("password1", error)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    identifier = forms.CharField(label=_("Email address or phone number"), max_length=254)
    password = forms.CharField(label=_("Password"), widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned_data = super().clean()
        identifier = cleaned_data.get("identifier")
        password = cleaned_data.get("password")
        if not identifier or not password:
            return cleaned_data

        if "@" in identifier:
            user = User.objects.filter(email=identifier.strip().lower()).first()
        else:
            user = User.objects.filter(phone=normalize_phone(identifier)).first()

        if user is None:
            # Hash anyway so a missing account takes as long as a wrong password.
            User().set_password(password)
        elif user.is_active and user.check_password(password):
            self.user = user
            return cleaned_data

        # One message for every failure, so it never reveals which accounts exist.
        raise ValidationError(_("Incorrect email address, phone number or password."))


class InstructorProfileForm(forms.ModelForm):
    """Teaching profile only. Email, phone and role are not editable here."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "headline", "bio", "website"]
        widgets = {"bio": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class StudentProfileForm(forms.ModelForm):
    """Personal details only. Email, phone and role are not editable here."""

    class Meta:
        model = User
        fields = ["first_name", "last_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class StyledPasswordChangeForm(PasswordChangeForm):
    """Django's own password change form, with Bootstrap styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class InstructorApplicationForm(forms.ModelForm):
    """Only the applicant's answers. User, status and review fields are set in code."""

    class Meta:
        model = InstructorApplication
        fields = ["full_name", "expertise", "biography", "teaching_experience", "reason", "portfolio_url"]
        widgets = {
            "biography": forms.Textarea(attrs={"rows": 4}),
            "teaching_experience": forms.Textarea(attrs={"rows": 4}),
            "reason": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
