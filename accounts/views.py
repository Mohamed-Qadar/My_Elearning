from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import (
    InstructorApplicationForm,
    InstructorProfileForm,
    LoginForm,
    RegisterForm,
    StudentProfileForm,
    StyledPasswordChangeForm,
)
from .models import InstructorApplication, User


def instructor_required(view):
    """Login required, and only for users with the Instructor role."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.role != User.Role.INSTRUCTOR:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def register(request):
    if request.user.is_authenticated:
        return redirect("learning:dashboard")

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, _("Your account has been created. Welcome!"))
        return redirect("learning:dashboard")
    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("learning:dashboard")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.user)
        # Only follow ?next= when it points back to this site.
        next_url = request.GET.get("next", "")
        if url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(next_url)
        return redirect("learning:dashboard")
    return render(request, "accounts/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, _("You have been logged out."))
    return redirect("core:home")


@login_required
def instructor_application(request):
    """Shows the user's latest application and, when allowed, the form to apply."""
    user = request.user
    application = user.instructor_applications.first()  # newest first
    has_pending = application is not None and application.status == InstructorApplication.Status.PENDING
    can_apply = user.is_student and not has_pending

    form = None
    if can_apply:
        form = InstructorApplicationForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            new_application = form.save(commit=False)
            new_application.user = user
            new_application.save()
            messages.success(request, "Your application has been submitted. We will review it soon.")
            return redirect("accounts:instructor_application")
    elif request.method == "POST":
        messages.error(request, "You cannot submit an instructor application.")
        return redirect("accounts:instructor_application")

    context = {"application": application, "form": form}
    return render(request, "accounts/instructor_application.html", context)


@login_required
def profile(request):
    """The user's own profile and password. Instructors also edit their teaching profile.

    The page holds two forms; the password form is sent with a "change_password" button.
    """
    is_instructor = request.user.role == User.Role.INSTRUCTOR
    ProfileForm = InstructorProfileForm if is_instructor else StudentProfileForm
    changing_password = "change_password" in request.POST
    saving_profile = request.method == "POST" and not changing_password

    form = ProfileForm(request.POST if saving_profile else None, instance=request.user)
    password_form = StyledPasswordChangeForm(request.user, request.POST if changing_password else None)
    if saving_profile and form.is_valid():
        form.save()
        messages.success(request, _("Your profile has been saved."))
        return redirect("accounts:profile")
    if changing_password and password_form.is_valid():
        password_form.save()
        update_session_auth_hash(request, password_form.user)  # keeps the user logged in
        messages.success(request, _("Your password has been changed."))
        return redirect("accounts:profile")

    context = {
        "form": form,
        "password_form": password_form,
        "base_template": "instructor/base.html" if is_instructor else "student/base.html",
    }
    return render(request, "accounts/profile.html", context)
