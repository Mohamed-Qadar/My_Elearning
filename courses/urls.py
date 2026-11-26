from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    # Public catalog
    path("courses/", views.catalog, name="catalog"),
    path("courses/<int:pk>/", views.detail, name="detail"),
    # Instructor dashboard
    path("instructor/", views.dashboard, name="dashboard"),
    path("instructor/courses/", views.course_list, name="course_list"),
    path("instructor/courses/new/", views.course_edit, name="course_create"),
    path("instructor/courses/<int:pk>/", views.course_detail, name="course_detail"),
    path("instructor/courses/<int:pk>/edit/", views.course_edit, name="course_edit"),
    path("instructor/courses/<int:pk>/publish/", views.course_publish, name="course_publish"),
    path("instructor/courses/<int:pk>/content/", views.course_content, name="course_content"),
    path("instructor/students/", views.students, name="students"),
    # Sections and lessons
    path("instructor/sections/<int:pk>/edit/", views.section_edit, name="section_edit"),
    path("instructor/sections/<int:pk>/delete/", views.section_delete, name="section_delete"),
    path("instructor/sections/<int:pk>/move/", views.section_move, name="section_move"),
    path("instructor/sections/<int:section_pk>/lessons/new/", views.lesson_create, name="lesson_create"),
    path("instructor/lessons/<int:pk>/edit/", views.lesson_edit, name="lesson_edit"),
    path("instructor/lessons/<int:pk>/delete/", views.lesson_delete, name="lesson_delete"),
    path("instructor/lessons/<int:pk>/move/", views.lesson_move, name="lesson_move"),
    # Materials
    path("instructor/courses/<int:course_pk>/materials/add/", views.material_upload, name="material_upload"),
    path("instructor/materials/<int:pk>/replace/", views.material_replace, name="material_replace"),
    path("instructor/materials/<int:pk>/delete/", views.material_delete, name="material_delete"),
    path("materials/<int:pk>/download/", views.material_download, name="material_download"),
]
