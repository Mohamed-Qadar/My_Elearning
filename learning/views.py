from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from courses.models import Course, Lesson, youtube_video_id

from .models import Enrollment, LessonProgress


def has_full_access(user, course):
    """The course's own instructor, or a student with an active enrollment in a published course.

    Being a superuser or staff member gives no access here: administration happens in Django Admin.
    """
    if not user.is_authenticated:
        return False
    if course.instructor_id == user.pk:
        return True
    is_published = course.status == Course.Status.PUBLISHED
    return is_published and Enrollment.active_for(user).filter(course=course).exists()


def course_lessons(course):
    """All lessons of a course in the order students follow them."""
    return list(Lesson.objects.filter(section__course=course).order_by("section__order", "section", "order", "id"))


def enrollments_with_progress(user):
    """The user's own active enrollments, each with total, done and percent of lessons."""
    completed = Q(
        course__sections__lessons__progress__student=user,
        course__sections__lessons__progress__completed_at__isnull=False,
    )
    enrollments = list(
        Enrollment.active_for(user).filter(course__status=Course.Status.PUBLISHED)
        .select_related("course__category", "course__instructor")
        .annotate(
            total=Count("course__sections__lessons", distinct=True),
            done=Count("course__sections__lessons__progress", filter=completed, distinct=True),
        )
    )
    for enrollment in enrollments:
        enrollment.percent = enrollment.done * 100 // enrollment.total if enrollment.total else 0
    return enrollments


# ---------- Dashboard and my courses ----------


@login_required
def dashboard(request):
    enrollments = enrollments_with_progress(request.user)
    context = {
        "enrollments": enrollments[:3],
        "enrolled_count": len(enrollments),
        "finished_count": sum(1 for e in enrollments if e.total and e.done == e.total),
        "completed_lessons": sum(e.done for e in enrollments),
        "recent_lessons": LessonProgress.objects.filter(
            student=request.user, lesson__section__course__in=[e.course_id for e in enrollments]
        ).select_related("lesson__section__course")[:5],
        "new_courses": Course.published().exclude(enrollments__student=request.user)[:3],
    }
    return render(request, "student/dashboard.html", context)


@login_required
def my_courses(request):
    return render(request, "student/my_courses.html", {"enrollments": enrollments_with_progress(request.user)})


# ---------- Enrolling ----------


@require_POST
@login_required
def enroll(request, pk):
    """Student accounts and free courses only.

    Instructors, moderators, staff and superusers cannot enroll here, and paid
    courses need the payment workflow, which does not exist yet.
    """
    course = get_object_or_404(Course.published(), pk=pk)
    if not request.user.is_student:
        messages.error(request, _("Only student accounts can enroll in courses."))
    elif not course.is_free:
        # The price is read from the database; nothing in the request can change it.
        messages.error(request, _("This course is not free. Online payment is not available yet."))
    else:
        Enrollment.objects.get_or_create(student=request.user, course=course)
        messages.success(request, _("You are enrolled. Enjoy the course!"))
        return redirect("learning:course_learn", pk=course.pk)
    return redirect("courses:detail", pk=course.pk)


# ---------- Learning ----------


@login_required
def course_learn(request, pk):
    """Continue learning: opens the first lesson the student has not completed."""
    course = get_object_or_404(Course, pk=pk)
    if not has_full_access(request.user, course):
        if course.status != Course.Status.PUBLISHED:
            raise Http404
        messages.info(request, _("Enroll in this course to start learning."))
        return redirect("courses:detail", pk=course.pk)

    lessons = course_lessons(course)
    if not lessons:
        messages.info(request, _("This course has no lessons yet."))
        return redirect("courses:detail", pk=course.pk)
    completed_ids = set(
        LessonProgress.objects.filter(student=request.user, lesson__in=lessons, completed_at__isnull=False)
        .values_list("lesson_id", flat=True)
    )
    next_lesson = next((lesson for lesson in lessons if lesson.pk not in completed_ids), lessons[0])
    return redirect("learning:lesson", pk=next_lesson.pk)


def lesson(request, pk):
    """The lesson player. Open to everyone for free previews, otherwise to people with access."""
    lesson = get_object_or_404(Lesson.objects.select_related("section__course__instructor"), pk=pk)
    course = lesson.section.course
    user = request.user
    full_access = has_full_access(user, course)
    is_preview = lesson.is_free_preview and course.status == Course.Status.PUBLISHED

    if not full_access and not is_preview:
        if course.status != Course.Status.PUBLISHED:
            raise Http404
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        messages.info(request, _("Enroll in this course to open this lesson."))
        return redirect("courses:detail", pk=course.pk)

    # Progress is kept for enrolled students only, never for visitors or the instructor.
    is_enrolled = Enrollment.active_for(user).filter(course=course).exists()
    completed_ids = set()
    if is_enrolled:
        progress, _created = LessonProgress.objects.get_or_create(student=user, lesson=lesson)
        progress.save()  # refreshes last_accessed_at
        completed_ids = set(
            LessonProgress.objects.filter(
                student=user, lesson__section__course=course, completed_at__isnull=False
            ).values_list("lesson_id", flat=True)
        )

    lessons = course_lessons(course)
    # Visitors on a free preview can only move between the other free previews.
    open_lessons = [item for item in lessons if full_access or item.is_free_preview]
    position = open_lessons.index(lesson)
    materials = []
    if full_access:
        whole_course = Q(lesson__isnull=True, section__isnull=True)
        materials = course.materials.filter(Q(lesson=lesson) | Q(section=lesson.section) | whole_course)

    context = {
        "lesson": lesson,
        "course": course,
        "sections": course.sections.prefetch_related("lessons"),
        "video_id": youtube_video_id(lesson.youtube_url),
        "materials": materials,
        "full_access": full_access,
        "is_enrolled": is_enrolled,
        "is_completed": lesson.pk in completed_ids,
        "completed_ids": completed_ids,
        "previous_lesson": open_lessons[position - 1] if position > 0 else None,
        "next_lesson": open_lessons[position + 1] if position + 1 < len(open_lessons) else None,
        "total": len(lessons),
        "done": len(completed_ids),
        "percent": len(completed_ids) * 100 // len(lessons),
    }
    return render(request, "student/lesson_player.html", context)


@require_POST
@login_required
def lesson_complete(request, pk):
    """Mark a lesson as completed, or undo it. For enrolled students only."""
    lesson = get_object_or_404(Lesson.objects.select_related("section__course"), pk=pk)
    course = lesson.section.course
    enrolled = Enrollment.active_for(request.user).filter(course=course).exists()
    if not enrolled or course.status != Course.Status.PUBLISHED:
        raise Http404

    progress, _created = LessonProgress.objects.get_or_create(student=request.user, lesson=lesson)
    progress.completed_at = None if progress.completed_at else timezone.now()
    progress.save()
    if progress.completed_at:
        messages.success(request, _("Lesson completed."))
        lessons = course_lessons(course)
        position = lessons.index(lesson)
        if position + 1 < len(lessons):
            return redirect("learning:lesson", pk=lessons[position + 1].pk)
    return redirect("learning:lesson", pk=lesson.pk)
