from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from courses.models import Category, Course
from learning.models import Enrollment

from .models import Payment

PASSWORD = "Str0ng-Passw0rd!"


class PaymentRecordTests(TestCase):
    """The payments app only stores records for now. Nothing in the site creates or edits them."""

    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(email="teacher@example.com", password=PASSWORD, role="instructor")
        cls.student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        cls.superuser = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        cls.course = Course.objects.create(
            instructor=cls.instructor, category=Category.objects.create(name="Test category"), title="Paid Physics",
            description="About physics.", learning_objectives="One", price="25.00", status=Course.Status.PUBLISHED,
        )

    def make_payment(self, **fields):
        return Payment.objects.create(student=self.student, course=self.course, amount="25.00", currency="USD", **fields)

    def test_payment_starts_pending_and_keeps_its_own_amount(self):
        payment = self.make_payment()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        Course.objects.filter(pk=self.course.pk).update(price="40.00")
        payment.refresh_from_db()
        self.assertEqual(str(payment.amount), "25.00")

    def test_a_payment_record_alone_does_not_open_the_course(self):
        self.make_payment(status=Payment.Status.PAID)
        self.assertFalse(Enrollment.objects.exists())
        self.client.force_login(self.student)
        response = self.client.get(reverse("learning:course_learn", args=[self.course.pk]))
        self.assertRedirects(response, reverse("courses:detail", args=[self.course.pk]))

    def test_trying_to_enroll_creates_no_payment(self):
        self.client.force_login(self.student)
        self.client.post(reverse("learning:enroll", args=[self.course.pk]), {"paid": "1", "status": "paid"})
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(Enrollment.objects.exists())

    def test_admin_is_read_only_even_for_a_superuser(self):
        payment = self.make_payment()
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("admin:payments_payment_changelist")).status_code, 200)
        data = {"student": self.student.pk, "course": self.course.pk, "amount": "1", "currency": "USD", "status": "paid"}
        self.assertEqual(self.client.post(reverse("admin:payments_payment_add"), data).status_code, 403)
        self.client.post(reverse("admin:payments_payment_change", args=[payment.pk]), data)
        delete_url = reverse("admin:payments_payment_delete", args=[payment.pk])
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        payment.refresh_from_db()
        self.assertEqual((payment.status, str(payment.amount)), (Payment.Status.PENDING, "25.00"))
        self.assertEqual(Payment.objects.count(), 1)

    def test_there_are_no_payment_pages_yet(self):
        from . import urls
        self.assertEqual(urls.urlpatterns, [])
