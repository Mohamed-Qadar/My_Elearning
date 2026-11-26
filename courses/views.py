from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.views import instructor_required
from learning.models import Enrollment

from .forms import CourseForm, LessonForm, MaterialForm, SectionForm
from .models import Category, Course, Lesson, Material, Section

# Every instructor view looks objects up through instructor=request.user,
# so another instructor's course, section, lesson or material is a 404.


def form_errors(form):
    """All error messages of a form as one sentence, for a flash message."""
    return " ".join(error for errors in form.errors.values() for error in errors)


def move_item(item, siblings, direction):
    """Move an item one place up or down among its siblings and renumber them."""
    items = list(siblings)
    index = items.index(item)
    new_index = index - 1 if direction == "up" else index + 1
    if 0 <= new_index < len(items):
        items[index], items[new_index] = items[new_index], items[index]
    for position, sibling in enumerate(items, start=1):
        if sibling.order != position:
            sibling.order = position
            sibling.save(update_fields=["order"])


def next_order(siblings):
    last = siblings.last()
    return last.order + 1 if last else 1


def content_url(course, anchor=""):
    return reverse("courses:course_content", args=[course.pk]) + anchor


# ---------- Public catalog ----------


def catalog(request):
    """Published courses, with search by title and three filters."""
    courses = Course.published()
    search = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    language = request.GET.get("language", "")
    level = request.GET.get("level", "")
    if search:
        courses = courses.filter(title__icontains=search)
    if category.isdigit():
        courses = courses.filter(category_id=category)
    if language in Course.Language.values:
        courses = courses.filter(language=language)
    if level in Course.Level.values:
        courses = courses.filter(level=level)

    page = Paginator(courses, 9).get_page(request.GET.get("page"))
    filters = request.GET.copy()
    filters.pop("page", None)
    context = {
        "page": page,
        "search": search,
        "selected_category": category,
        "selected_language": language,
        "selected_level": level,
        "categories": Category.objects.filter(courses__status=Course.Status.PUBLISHED).distinct(),
        "languages": Course.Language.choices,
        "levels": Course.Level.choices,
        "filter_query": filters.urlencode(),  # keeps the filters in the page links
        "is_filtered": bool(search or category or language or level),
    }
    return render(request, "courses/catalog.html", context)


def detail(request, pk):
    """Public page of a published course. Shows titles only: no notes, files or video links."""
    course = get_object_or_404(Course.published(), pk=pk)
    user = request.user
    context = {
        "course": course,
        "sections": course.sections.prefetch_related("lessons"),
        "lesson_count": Lesson.objects.filter(section__course=course).count(),
        "student_count": course.enrollments.count(),
        "is_owner": user.is_authenticated and course.instructor_id == user.pk,
        "is_enrolled": Enrollment.active_for(user).filter(course=course).exists(),
    }
    return render(request, "courses/detail.html", context)


# ---------- Dashboard and courses ----------


@instructor_required
def dashboard(request):
    courses = Course.objects.filter(instructor=request.user)
    context = {
        "total_courses": courses.count(),
        "published_courses": courses.filter(status=Course.Status.PUBLISHED).count(),
        "draft_courses": courses.filter(status=Course.Status.DRAFT).count(),
        "total_students": Enrollment.objects.filter(course__instructor=request.user)
        .values("student")
        .distinct()
        .count(),
        "recent_courses": courses[:5],
    }
    return render(request, "instructor/dashboard.html", context)


@instructor_required
def course_list(request):
    courses = Course.objects.filter(instructor=request.user).annotate(
        lesson_count=Count("sections__lessons", distinct=True),
        student_count=Count("enrollments", distinct=True),
    )
    return render(request, "instructor/courses.html", {"courses": courses})


@instructor_required
def course_edit(request, pk=None):
    """Create a course (no pk) or edit one of the instructor's own courses."""
    course = get_object_or_404(Course, pk=pk, instructor=request.user) if pk else None
    form = CourseForm(request.POST or None, request.FILES or None, instance=course)
    if request.method == "POST" and form.is_valid():
        is_new = course is None
        course = form.save(commit=False)
        course.instructor = request.user
        course.save()
        if is_new:
            messages.success(request, _("Course saved as a draft. Now add sections and lessons."))
            return redirect("courses:course_content", pk=course.pk)
        messages.success(request, _("Course details saved."))
        return redirect("courses:course_detail", pk=course.pk)
    # The form is shown as three cards: (heading, fields, show in two columns).
    field_groups = [
        (_("Basic information"), [form["title"], form["description"]], False),
        (_("Course details"), [form["category"], form["language"], form["level"], form["price"]], True),
        (_("Thumbnail and objectives"), [form["thumbnail"], form["learning_objectives"]], False),
    ]
    context = {"form": form, "course": course, "field_groups": field_groups}
    return render(request, "instructor/course_form.html", context)


@instructor_required
def course_detail(request, pk):
    course = get_object_or_404(Course, pk=pk, instructor=request.user)
    context = {
        "course": course,
        "section_count": course.sections.count(),
        "lesson_count": Lesson.objects.filter(section__course=course).count(),
        "material_count": course.materials.count(),
        "student_count": course.enrollments.count(),
    }
    return render(request, "instructor/course_detail.html", context)


@require_POST
@instructor_required
def course_publish(request, pk):
    """Publish or unpublish, depending on the posted 'publish' value."""
    course = get_object_or_404(Course, pk=pk, instructor=request.user)
    if request.POST.get("publish") != "yes":
        course.status = Course.Status.DRAFT
        messages.success(request, _("Course unpublished. It is a draft again."))
    elif not Lesson.objects.filter(section__course=course).exists():
        messages.error(request, _("Add at least one lesson before publishing this course."))
    else:
        course.status = Course.Status.PUBLISHED
        messages.success(request, _("Course published."))
    course.save()  # save() also sets or clears the publication date
    return redirect("courses:course_detail", pk=course.pk)


# ---------- Sections and lessons ----------


@instructor_required
def course_content(request, pk):
    """Lists sections, lessons and materials. A POST adds a new section."""
    course = get_object_or_404(Course, pk=pk, instructor=request.user)
    section_form = SectionForm(request.POST or None)
    if request.method == "POST" and section_form.is_valid():
        section = section_form.save(commit=False)
        section.course = course
        section.order = next_order(course.sections)
        section.save()
        messages.success(request, _("Section added."))
        return redirect(content_url(course))
    context = {
        "course": course,
        "sections": course.sections.prefetch_related("lessons"),
        "section_form": section_form,
        "materials": course.materials.select_related("section", "lesson"),
        "material_form": MaterialForm(course),
    }
    return render(request, "instructor/lessons.html", context)


@require_POST
@instructor_required
def section_edit(request, pk):
    section = get_object_or_404(Section, pk=pk, course__instructor=request.user)
    form = SectionForm(request.POST, instance=section)
    if form.is_valid():
        form.save()
        messages.success(request, _("Section renamed."))
    else:
        messages.error(request, form_errors(form))
    return redirect(content_url(section.course))


@require_POST
@instructor_required
def section_delete(request, pk):
    section = get_object_or_404(Section, pk=pk, course__instructor=request.user)
    section.delete()
    messages.success(request, _("Section deleted."))
    return redirect(content_url(section.course))


@require_POST
@instructor_required
def section_move(request, pk):
    section = get_object_or_404(Section, pk=pk, course__instructor=request.user)
    move_item(section, section.course.sections.all(), request.POST.get("direction"))
    return redirect(content_url(section.course))


@instructor_required
def lesson_create(request, section_pk):
    section = get_object_or_404(Section, pk=section_pk, course__instructor=request.user)
    form = LessonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lesson = form.save(commit=False)
        lesson.section = section
        lesson.order = next_order(section.lessons)
        lesson.save()
        messages.success(request, _("Lesson added."))
        return redirect(content_url(section.course))
    context = {"form": form, "section": section, "course": section.course}
    return render(request, "instructor/lesson_form.html", context)


@instructor_required
def lesson_edit(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk, section__course__instructor=request.user)
    form = LessonForm(request.POST or None, instance=lesson)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Lesson saved."))
        return redirect(content_url(lesson.section.course))
    context = {"form": form, "lesson": lesson, "section": lesson.section, "course": lesson.section.course}
    return render(request, "instructor/lesson_form.html", context)


@require_POST
@instructor_required
def lesson_delete(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk, section__course__instructor=request.user)
    lesson.delete()
    messages.success(request, _("Lesson deleted."))
    return redirect(content_url(lesson.section.course))


@require_POST
@instructor_required
def lesson_move(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk, section__course__instructor=request.user)
    move_item(lesson, lesson.section.lessons.all(), request.POST.get("direction"))
    return redirect(content_url(lesson.section.course))


# ---------- Materials ----------


@require_POST
@instructor_required
def material_upload(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    form = MaterialForm(course, request.POST, request.FILES)
    if form.is_valid():
        material = form.save(commit=False)
        material.course = course
        material.save()
        messages.success(request, _("Material uploaded."))
    else:
        messages.error(request, form_errors(form))
    return redirect(content_url(course, "#materials"))


@require_POST
@instructor_required
def material_replace(request, pk):
    """Swap the file of a material. Title and attachment stay as they are."""
    material = get_object_or_404(Material, pk=pk, course__instructor=request.user)
    new_file = request.FILES.get("file")
    if new_file is None:
        messages.error(request, _("Choose a file to upload."))
        return redirect(content_url(material.course, "#materials"))

    old_name = material.file.name
    material.file = new_file
    try:
        material.full_clean()  # runs the same type, size and content checks as an upload
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        material.save()
        material.file.storage.delete(old_name)
        messages.success(request, _("File replaced."))
    return redirect(content_url(material.course, "#materials"))


@require_POST
@instructor_required
def material_delete(request, pk):
    material = get_object_or_404(Material, pk=pk, course__instructor=request.user)
    material.delete()  # the file itself is removed by a signal in models.py
    messages.success(request, _("Material deleted."))
    return redirect(content_url(material.course, "#materials"))


@login_required
def material_download(request, pk):
    """The only way to get a material file: for the owner or an enrolled student.

    With ?view=1 a PDF or text file opens in the browser instead of downloading.
    """
    material = get_object_or_404(Material.objects.select_related("course"), pk=pk)
    user = request.user
    is_owner = material.course.instructor_id == user.pk
    is_enrolled = Enrollment.active_for(user).filter(course=material.course).exists()
    if not (is_owner or is_enrolled):
        raise Http404
    download = not (request.GET.get("view") and material.can_be_viewed)
    try:
        return FileResponse(material.file.open("rb"), as_attachment=download, filename=material.filename)
    except FileNotFoundError:
        raise Http404


# ---------- Students ----------


@instructor_required
def students(request):
    enrollments = Enrollment.objects.filter(course__instructor=request.user).select_related("student", "course")
    return render(request, "instructor/students.html", {"enrollments": enrollments})
