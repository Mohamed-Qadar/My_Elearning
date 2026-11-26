from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class Enrollment(models.Model):
    """A student's access to a course.

    There are two ways to get one today, recorded in "source":
    - free: the student enrolled in a free course.
    - manual: a superuser granted access by hand in Django Admin. This is not a payment.
    A third source, a verified payment, will be added together with the payment provider.
    """

    class Source(models.TextChoices):
        FREE = "free", "Free enrollment"
        MANUAL = "manual", "Granted by an administrator (no payment)"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments")
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="enrollments")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.FREE)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="granted_enrollments"
    )
    # Filled in by save() when a student joins a course that is free at that moment.
    # It lets that student keep access if the course gets a price later.
    joined_free_course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, null=True, blank=True, editable=False, related_name="+"
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-enrolled_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["student", "course"], name="one_enrollment_per_student_and_course"),
            # The record of joining freely belongs to one course and cannot be carried to another.
            models.CheckConstraint(
                condition=models.Q(joined_free_course__isnull=True) | models.Q(joined_free_course=models.F("course")),
                name="joined_free_course_is_the_enrolled_course",
            ),
            models.CheckConstraint(
                condition=models.Q(source="free", granted_by__isnull=True)
                | models.Q(source="manual", granted_by__isnull=False),
                name="manual_enrollment_names_who_granted_it",
            ),
        ]

    def __str__(self):
        return f"{self.student} in {self.course}"

    @classmethod
    def active_for(cls, user):
        """The enrollments that open a course for "user" right now.

        Every page that gives student access asks here, so a row that reached the table
        without save() (bulk_create, update, raw SQL) opens nothing unless it is valid:
        - the account must be a Student account today, whatever it was when it enrolled;
        - a free enrollment opens a course that is free today, or one the student
          joined through save() while it was free (joined_free_course);
        - a manual grant must name who granted it.
        Rows that do not qualify are kept as history and open again if they qualify later.
        """
        if not user.is_authenticated or not user.is_student:
            return cls.objects.none()
        still_free_or_joined_free = models.Q(course__price=0) | models.Q(joined_free_course__isnull=False)
        free = models.Q(source=cls.Source.FREE) & still_free_or_joined_free
        manual = models.Q(source=cls.Source.MANUAL, granted_by__isnull=False)
        return cls.objects.filter(free | manual, student=user)

    def clean(self):
        """The enrollment rules. Forms call this, and so does save().

        It also sets joined_free_course, so a value passed in by the caller is never used.
        """
        if not self.student_id or not self.course_id:
            return
        if not self.student.is_student:
            raise ValidationError({"student": _("Only student accounts can enroll in courses.")})
        # Whether this student joined freely is read from the stored row, never from the caller.
        stored = Enrollment.objects.filter(pk=self.pk, student=self.student_id, source=self.Source.FREE)
        joined_free = self.pk is not None and stored.filter(joined_free_course=self.course_id).exists()
        is_free_enrollment = self.source == self.Source.FREE
        if is_free_enrollment and not (self.course.is_free or joined_free):
            raise ValidationError(_("A paid course cannot be joined through free enrollment."))
        if self.source == self.Source.FREE and self.granted_by_id:
            raise ValidationError(_("A free enrollment is not granted by anyone."))
        if self.source == self.Source.MANUAL and not (self.granted_by_id and self.granted_by.is_superuser):
            raise ValidationError(_("Only a superuser can grant an enrollment by hand."))
        self.joined_free_course_id = self.course_id if is_free_enrollment else None

    def save(self, *args, **kwargs):
        # Checked on every save, new or changed, so code that writes an enrollment
        # directly (create, get_or_create, update_or_create) cannot skip the rules.
        self.clean()
        super().save(*args, **kwargs)


class LessonProgress(models.Model):
    """One row per student and lesson: when it was last opened and whether it is completed."""

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_progress")
    lesson = models.ForeignKey("courses.Lesson", on_delete=models.CASCADE, related_name="progress")
    last_accessed_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_accessed_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["student", "lesson"], name="one_progress_row_per_student_and_lesson"),
        ]

    def __str__(self):
        return f"{self.student}: {self.lesson}"
