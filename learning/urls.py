from django.urls import path

from . import views

app_name = "learning"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("courses/", views.my_courses, name="my_courses"),
    path("courses/<int:pk>/enroll/", views.enroll, name="enroll"),
    path("courses/<int:pk>/learn/", views.course_learn, name="course_learn"),
    path("lessons/<int:pk>/", views.lesson, name="lesson"),
    path("lessons/<int:pk>/complete/", views.lesson_complete, name="lesson_complete"),
]
