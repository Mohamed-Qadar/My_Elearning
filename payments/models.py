from django.conf import settings
from django.db import models


class Payment(models.Model):
    """A record of one payment for one course.

    Nothing creates these yet: no payment provider is connected. The model exists
    so a provider can be added later without changing courses or enrollments.
    The amount and currency are copied from the course when the payment starts,
    so a later price change never alters an old payment.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    course = models.ForeignKey("courses.Course", on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # Filled in by the future integration: which provider, and its own transaction id.
    provider = models.CharField(max_length=50, blank=True)
    provider_reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.student} - {self.course}: {self.amount} {self.currency} ({self.get_status_display()})"
