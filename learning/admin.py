from django import forms
from django.contrib import admin

from .models import Enrollment, LessonProgress


class ManualEnrollmentForm(forms.ModelForm):
    """Marks the new enrollment as a manual grant before the model's rules are checked."""

    granted_by = None  # set for each request by EnrollmentAdmin.get_form

    def clean(self):
        self.instance.source = Enrollment.Source.MANUAL
        self.instance.granted_by = self.granted_by
        return super().clean()


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    """An enrollment opens a course, including a paid one, so only superusers may grant or
    remove one by hand. A grant is recorded as "manual" with the superuser's name: it is not
    a payment and creates no payment record. Enrollments cannot be edited afterwards.
    """

    form = ManualEnrollmentForm
    fields = ["student", "course"]
    list_display = ["student", "course", "source", "granted_by", "enrolled_at"]
    list_filter = ["source"]
    search_fields = ["student__email", "student__phone", "course__title"]
    autocomplete_fields = ["student", "course"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.granted_by = request.user
        return form

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ["student", "lesson", "last_accessed_at", "completed_at"]
    search_fields = ["student__email", "student__phone", "lesson__title"]
    raw_id_fields = ["student", "lesson"]
