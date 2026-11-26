from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Read-only. Payments must come from a payment provider, never from a person typing them in."""

    list_display = ["student", "course", "amount", "currency", "status", "provider", "created_at", "paid_at"]
    list_filter = ["status", "provider", "currency"]
    search_fields = ["student__email", "student__phone", "course__title", "provider_reference"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
