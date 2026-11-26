from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import InstructorApplication, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Django's user admin, adjusted because this User has no username."""

    ordering = ["id"]
    list_display = ["email", "phone", "role", "is_staff", "is_superuser", "is_active"]
    list_filter = ["role", "is_staff", "is_superuser", "is_active"]
    search_fields = ["email", "phone"]
    fieldsets = [
        (None, {"fields": ["email", "phone", "password"]}),
        ("Personal info", {"fields": ["first_name", "last_name"]}),
        ("Role and permissions", {"fields": ["role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions"]}),
        ("Important dates", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [
        (None, {"classes": ["wide"], "fields": ["email", "phone", "usable_password", "password1", "password2"]}),
    ]

    def get_readonly_fields(self, request, obj=None):
        # Only a superuser may hand out admin access or permissions.
        if request.user.is_superuser:
            return []
        return ["is_staff", "is_superuser", "groups", "user_permissions"]

    def has_change_permission(self, request, obj=None):
        # Also guards the password-change page, which uses this check.
        allowed = super().has_change_permission(request, obj)
        return allowed and self.may_manage(request, obj)

    def has_delete_permission(self, request, obj=None):
        allowed = super().has_delete_permission(request, obj)
        return allowed and self.may_manage(request, obj)

    def may_manage(self, request, obj):
        """Staff who are not superusers cannot manage superusers or themselves."""
        if obj is None or request.user.is_superuser:
            return True
        return not obj.is_superuser and obj != request.user


@admin.register(InstructorApplication)
class InstructorApplicationAdmin(admin.ModelAdmin):
    """Applications are read-only here. Decisions are made with the two actions."""

    list_display = ["full_name", "user", "status", "submitted_at", "reviewed_at", "reviewed_by"]
    list_filter = ["status"]
    search_fields = ["full_name", "user__email", "user__phone"]
    fieldsets = [
        ("Applicant", {"fields": ["user", "full_name", "expertise", "portfolio_url"]}),
        ("Application", {"fields": ["biography", "teaching_experience", "reason"]}),
        ("Review", {"fields": ["status", "submitted_at", "reviewed_at", "reviewed_by"]}),
    ]
    actions = ["approve_applications", "reject_applications"]

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Approve selected pending applications", permissions=["change"])
    def approve_applications(self, request, queryset):
        self.review(request, queryset, approved=True)

    @admin.action(description="Reject selected pending applications", permissions=["change"])
    def reject_applications(self, request, queryset):
        self.review(request, queryset, approved=False)

    def review(self, request, queryset, approved):
        # Already reviewed applications are skipped, and nobody reviews their own.
        pending = queryset.filter(status=InstructorApplication.Status.PENDING).exclude(user=request.user)
        for application in pending:
            application.review(request.user, approved)
        decision = "approved" if approved else "rejected"
        self.message_user(request, f"{len(pending)} application(s) {decision}.")
