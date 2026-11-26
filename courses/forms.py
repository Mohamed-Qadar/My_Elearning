from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .models import MATERIAL_EXTENSIONS, Course, Lesson, Material, Section


def add_bootstrap_classes(form):
    for field in form.fields.values():
        if isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs["class"] = "form-check-input"
        elif isinstance(field.widget, forms.Select):
            field.widget.attrs["class"] = "form-select"
        else:
            field.widget.attrs["class"] = "form-control"


class CourseForm(forms.ModelForm):
    """The instructor and the publication status are set in the views."""

    class Meta:
        model = Course
        fields = [
            "title",
            "description",
            "category",
            "language",
            "level",
            "price",
            "thumbnail",
            "learning_objectives",
        ]
        # Labels for the fields whose model does not already carry a translated name.
        labels = {
            "title": _("Title"),
            "description": _("Description"),
            "category": _("Category"),
            "level": _("Level"),
            "learning_objectives": _("Learning objectives"),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "learning_objectives": forms.Textarea(attrs={"rows": 5}),
            "thumbnail": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].empty_label = _("Choose a category")
        self.fields["price"].label = _("Price (%(currency)s)") % {"currency": settings.CURRENCY_CODE}
        add_bootstrap_classes(self)


class SectionForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ["title"]
        labels = {"title": _("Title")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ["title", "description", "youtube_url", "notes", "is_free_preview"]
        labels = {"title": _("Title"), "description": _("Description")}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)


class MaterialForm(forms.ModelForm):
    """Upload form. "Attach to" offers only this course's own sections and lessons."""

    attach_to = forms.ChoiceField(label=_("Attach to"), required=False)
    field_order = ["title", "attach_to", "file"]

    class Meta:
        model = Material
        fields = ["title", "file"]
        labels = {"title": _("Title"), "file": _("File")}

    def __init__(self, course, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", _("The whole course"))]
        for section in course.sections.prefetch_related("lessons"):
            choices.append((f"section-{section.pk}", _("Section: %(title)s") % {"title": section.title}))
            for lesson in section.lessons.all():
                choices.append((f"lesson-{lesson.pk}", _("\u2014 Lesson: %(title)s") % {"title": lesson.title}))
        self.fields["attach_to"].choices = choices
        # A hint for the file picker only. The server checks every file itself.
        self.fields["file"].widget.attrs["accept"] = ",".join(f".{ext}" for ext in MATERIAL_EXTENSIONS)
        add_bootstrap_classes(self)

    def save(self, commit=True):
        kind, _, pk = self.cleaned_data["attach_to"].partition("-")
        self.instance.section_id = int(pk) if kind == "section" else None
        self.instance.lesson_id = int(pk) if kind == "lesson" else None
        return super().save(commit)
