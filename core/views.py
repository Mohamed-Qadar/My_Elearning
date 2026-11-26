from django.db.models import Count, Q
from django.shortcuts import render

from courses.models import Category, Course


def home(request):
    """Public landing page. Only published courses are ever shown."""
    courses = Course.published()
    is_published = Q(courses__status=Course.Status.PUBLISHED)
    context = {
        # "Featured" means the published courses with the most students.
        "featured_courses": courses.annotate(student_count=Count("enrollments")).order_by(
            "-student_count", "-created_at"
        )[:3],
        "recent_courses": courses[:6],
        "categories": Category.objects.annotate(course_count=Count("courses", filter=is_published)).filter(
            course_count__gt=0
        ),
        "course_count": courses.count(),
        "instructor_count": courses.values("instructor").distinct().count(),
    }
    return render(request, "home.html", context)
