from django.contrib import admin

from .models import Category, Course


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["title", "instructor", "category", "status", "price", "created_at"]
    list_filter = ["status", "category", "language", "level"]
    search_fields = ["title", "instructor__email", "instructor__phone"]
