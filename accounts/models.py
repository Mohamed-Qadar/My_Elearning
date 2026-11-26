import re

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Numbers written without a country code are treated as Somali numbers.
DEFAULT_COUNTRY_CODE = "+252"


def normalize_phone(phone):
    """Return the phone as +<country code><number>, or None when empty."""
    phone = re.sub(r"[\s\-().]", "", phone or "")
    if not phone:
        return None
    if phone.startswith("00"):
        return "+" + phone[2:]
    if not phone.startswith("+"):
        return DEFAULT_COUNTRY_CODE + phone.lstrip("0")
    return phone


class UserManager(BaseUserManager):
    """Needed because the default manager requires a username."""

    def create_user(self, email=None, phone=None, password=None, **extra_fields):
        user = self.model(email=email, phone=phone, **extra_fields)
        user.set_password(password)
        user.full_clean()
        user.save()
        return user

    def create_superuser(self, email=None, phone=None, password=None, **extra_fields):
        """Used by createsuperuser, which may pass a blank email or a blank phone."""
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        return self.create_user(email=email, phone=phone, password=password, **extra_fields)


class User(AbstractUser):
    """A user signs in with an email address or a phone number."""

    class Role(models.TextChoices):
        # Super Admin is not a role: it is Django's is_superuser flag.
        STUDENT = "student", _("Student")
        INSTRUCTOR = "instructor", _("Instructor")
        MODERATOR = "moderator", _("Moderator")

    username = None
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    # Teaching profile, shown to students with an instructor's courses.
    headline = models.CharField(_("professional title"), max_length=150, blank=True)
    bio = models.TextField(_("biography"), blank=True)
    website = models.URLField(_("portfolio or website"), blank=True)

    USERNAME_FIELD = "email"
    # Makes createsuperuser ask for the phone too. Either prompt may be left blank.
    REQUIRED_FIELDS = ["phone"]

    objects = UserManager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email__isnull=False) | models.Q(phone__isnull=False),
                name="user_has_email_or_phone",
                violation_error_message=_("Enter an email address or a phone number."),
            ),
        ]

    def __str__(self):
        return self.email or self.phone

    @property
    def is_student(self):
        """An ordinary student: the Student role and no administrator access."""
        return self.role == self.Role.STUDENT and not self.is_staff and not self.is_superuser

    @property
    def display_name(self):
        """A name that is safe to show to other people: never the email or phone."""
        return self.get_full_name() or self.get_role_display()

    def clean(self):
        """Normalize email and phone. Runs for every form, including the admin.

        The "email or phone" rule is checked afterwards by the Meta constraint.
        """
        super().clean()
        self.email = (self.email or "").strip().lower() or None
        self.phone = normalize_phone(self.phone)
        if self.phone and not re.fullmatch(r"\+\d{8,15}", self.phone):
            raise ValidationError({"phone": _("Enter a valid phone number.")})


class InstructorApplication(models.Model):
    """A student's request to become an instructor, reviewed in the admin."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="instructor_applications")
    full_name = models.CharField(max_length=150)
    expertise = models.CharField("professional title or expertise", max_length=150)
    biography = models.TextField()
    teaching_experience = models.TextField()
    reason = models.TextField("why do you want to teach?")
    portfolio_url = models.URLField("portfolio or website", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_applications"
    )

    class Meta:
        ordering = ["-submitted_at", "-id"]
        constraints = [
            # A user can have only one pending application at a time.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="pending"),
                name="one_pending_application_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.get_status_display()})"

    def review(self, reviewer, approved):
        """Record the decision. Approval makes the applicant an instructor."""
        with transaction.atomic():
            self.status = self.Status.APPROVED if approved else self.Status.REJECTED
            self.reviewed_at = timezone.now()
            self.reviewed_by = reviewer
            self.save()
            if approved:
                # The application answers become the start of the teaching profile.
                self.user.role = User.Role.INSTRUCTOR
                self.user.headline = self.expertise
                self.user.bio = self.biography
                self.user.website = self.portfolio_url
                self.user.save(update_fields=["role", "headline", "bio", "website"])
