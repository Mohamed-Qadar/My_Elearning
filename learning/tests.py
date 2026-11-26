import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from courses.models import Category, Course, Lesson, Material, Section

from payments.models import Payment

from .models import Enrollment, LessonProgress

PASSWORD = "Str0ng-Passw0rd!"
PREVIEW_VIDEO = "dQw4w9WgXcQ"
PRIVATE_VIDEO = "abcdefghijk"
LOGIN_URL = reverse("accounts:login")
TEMP_MEDIA = Path(tempfile.mkdtemp())


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)


def make_course(instructor, category, title, **fields):
    fields.setdefault("status", Course.Status.PUBLISHED)
    return Course.objects.create(
        instructor=instructor,
        category=category,
        title=title,
        description=f"About {title}.",
        learning_objectives="Objective one\nObjective two",
        **fields,
    )


@override_settings(MEDIA_ROOT=TEMP_MEDIA / "public", PRIVATE_MEDIA_ROOT=TEMP_MEDIA / "private")
class PortalTestCase(TestCase):
    """A free course with a preview lesson and a private lesson, a paid course and a draft."""

    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            email="teacher@example.com", password=PASSWORD, role="instructor", first_name="Tina", last_name="Teacher"
        )
        cls.student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        cls.other_student = User.objects.create_user(email="other@example.com", password=PASSWORD)
        cls.owner = User.objects.create_superuser(email="owner@example.com", password=PASSWORD)
        cls.category = Category.objects.create(name="Test category")

        cls.free_course = make_course(cls.instructor, cls.category, "Free Algebra")
        cls.section = Section.objects.create(course=cls.free_course, title="Basics", order=1)
        cls.preview_lesson = Lesson.objects.create(
            section=cls.section, title="Welcome", order=1, is_free_preview=True,
            youtube_url=f"https://www.youtube.com/watch?v={PREVIEW_VIDEO}", notes="Preview notes for everyone.",
        )
        cls.private_lesson = Lesson.objects.create(
            section=cls.section, title="Equations", order=2,
            youtube_url=f"https://www.youtube.com/watch?v={PRIVATE_VIDEO}", notes="Private notes for students.",
        )
        cls.material = Material.objects.create(
            course=cls.free_course, lesson=cls.private_lesson, title="Worksheet",
            file=SimpleUploadedFile("worksheet.pdf", b"%PDF-1.4 test"),
        )

        cls.paid_course = make_course(cls.instructor, cls.category, "Paid Physics", price="25.00")
        cls.paid_section = Section.objects.create(course=cls.paid_course, title="Motion", order=1)
        cls.paid_lesson = Lesson.objects.create(section=cls.paid_section, title="Speed", order=1, notes="Paid notes.")

        cls.draft_course = make_course(cls.instructor, cls.category, "Draft Biology", status=Course.Status.DRAFT)
        cls.draft_section = Section.objects.create(course=cls.draft_course, title="Cells", order=1)
        cls.draft_lesson = Lesson.objects.create(
            section=cls.draft_section, title="The cell", order=1, is_free_preview=True, notes="Draft notes."
        )

    def lesson_url(self, lesson):
        return reverse("learning:lesson", args=[lesson.pk])

    def enroll(self, student=None, course=None):
        """A free enrollment, or for a paid course one granted by the superuser."""
        course = course or self.free_course
        grant = {} if course.is_free else {"source": Enrollment.Source.MANUAL, "granted_by": self.owner}
        return Enrollment.objects.create(student=student or self.student, course=course, **grant)


class DashboardTests(PortalTestCase):
    def test_dashboard_and_my_courses_require_login(self):
        for name in ["learning:dashboard", "learning:my_courses"]:
            url = reverse(name)
            self.assertRedirects(self.client.get(url), f"{LOGIN_URL}?next={url}")

    def test_new_student_sees_empty_state_not_placeholder(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("learning:dashboard"))
        self.assertContains(response, "You are not enrolled in any course yet.")
        self.assertNotContains(response, "Your dashboard will appear here")
        self.assertEqual(response.context["enrolled_count"], 0)

    def test_dashboard_shows_real_progress(self):
        self.enroll()
        LessonProgress.objects.create(student=self.student, lesson=self.preview_lesson, completed_at="2026-01-01T10:00Z")
        self.client.force_login(self.student)
        response = self.client.get(reverse("learning:dashboard"))
        enrollment = response.context["enrollments"][0]
        self.assertEqual((enrollment.total, enrollment.done, enrollment.percent), (2, 1, 50))
        self.assertEqual(response.context["completed_lessons"], 1)
        self.assertEqual(response.context["finished_count"], 0)
        self.assertContains(response, "Free Algebra")
        self.assertContains(response, "Welcome")  # recently opened lesson

    def test_students_see_only_their_own_enrollments_and_progress(self):
        self.enroll(self.other_student, self.paid_course)
        LessonProgress.objects.create(student=self.other_student, lesson=self.paid_lesson)
        self.enroll()
        self.client.force_login(self.student)
        for name in ["learning:dashboard", "learning:my_courses"]:
            response = self.client.get(reverse(name))
            titles = [enrollment.course.title for enrollment in response.context["enrollments"]]
            self.assertEqual(titles, ["Free Algebra"])
        dashboard = self.client.get(reverse("learning:dashboard"))
        self.assertEqual(list(dashboard.context["recent_lessons"]), [])

    def test_other_students_progress_does_not_count(self):
        self.enroll()
        LessonProgress.objects.create(student=self.other_student, lesson=self.preview_lesson, completed_at="2026-01-01T10:00Z")
        self.client.force_login(self.student)
        response = self.client.get(reverse("learning:my_courses"))
        self.assertEqual(response.context["enrollments"][0].done, 0)

    def test_enrolled_course_that_becomes_a_draft_is_hidden(self):
        self.enroll()
        Course.objects.filter(pk=self.free_course.pk).update(status=Course.Status.DRAFT)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("learning:my_courses")).context["enrollments"], [])
        self.assertEqual(self.client.get(self.lesson_url(self.private_lesson)).status_code, 404)


class EnrollmentTests(PortalTestCase):
    def enroll_url(self, course):
        return reverse("learning:enroll", args=[course.pk])

    def test_student_can_enroll_in_a_free_course(self):
        self.client.force_login(self.student)
        response = self.client.post(self.enroll_url(self.free_course))
        self.assertTrue(Enrollment.objects.filter(student=self.student, course=self.free_course).exists())
        self.assertEqual(response.url, reverse("learning:course_learn", args=[self.free_course.pk]))
        # Enrolling twice keeps one enrollment.
        self.client.post(self.enroll_url(self.free_course))
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_paid_course_cannot_be_enrolled_in(self):
        self.client.force_login(self.student)
        response = self.client.post(self.enroll_url(self.paid_course), follow=True)
        self.assertContains(response, "This course is not free. Online payment is not available yet.")
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_draft_course_cannot_be_enrolled_in(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(self.enroll_url(self.draft_course)).status_code, 404)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_enrolling_needs_login_post_and_csrf(self):
        url = self.enroll_url(self.free_course)
        self.assertRedirects(self.client.post(url), f"{LOGIN_URL}?next={url}")
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(url).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.student)
        self.assertEqual(strict.post(url).status_code, 403)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_instructor_does_not_enroll_in_own_course(self):
        self.client.force_login(self.instructor)
        self.client.post(self.enroll_url(self.free_course))
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_enrollment_cannot_be_created_for_someone_else(self):
        self.client.force_login(self.student)
        self.client.post(self.enroll_url(self.free_course), {"student": self.other_student.pk})
        self.assertEqual(list(Enrollment.objects.values_list("student", flat=True)), [self.student.pk])


class LessonAccessTests(PortalTestCase):
    def test_visitor_can_watch_a_free_preview(self):
        response = self.client.get(self.lesson_url(self.preview_lesson))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"youtube-nocookie.com/embed/{PREVIEW_VIDEO}")
        self.assertContains(response, "Preview notes for everyone.")
        self.assertContains(response, "This is a free preview.")
        # Nothing from the other lessons, and no files.
        self.assertNotContains(response, PRIVATE_VIDEO)
        self.assertNotContains(response, "Private notes")
        self.assertNotContains(response, "Worksheet")
        self.assertNotContains(response, self.lesson_url(self.private_lesson))

    def test_visitor_is_sent_to_login_for_other_lessons(self):
        url = self.lesson_url(self.private_lesson)
        self.assertRedirects(self.client.get(url), f"{LOGIN_URL}?next={url}")

    def test_student_who_is_not_enrolled_cannot_open_a_private_lesson(self):
        self.client.force_login(self.student)
        response = self.client.get(self.lesson_url(self.private_lesson), follow=True)
        self.assertRedirects(response, reverse("courses:detail", args=[self.free_course.pk]))
        self.assertContains(response, "Enroll in this course to open this lesson.")
        self.assertNotContains(response, PRIVATE_VIDEO)
        self.assertNotContains(response, "Private notes")

    def test_enrolled_student_gets_video_notes_and_materials(self):
        self.enroll()
        self.client.force_login(self.student)
        response = self.client.get(self.lesson_url(self.private_lesson))
        self.assertContains(response, f"youtube-nocookie.com/embed/{PRIVATE_VIDEO}")
        self.assertContains(response, "Private notes for students.")
        self.assertContains(response, "Worksheet")
        download = reverse("courses:material_download", args=[self.material.pk])
        self.assertContains(response, download)
        self.assertEqual(self.client.get(download).status_code, 200)

    def test_materials_are_not_downloadable_without_enrollment(self):
        download = reverse("courses:material_download", args=[self.material.pk])
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(download).status_code, 404)
        # Being enrolled in another course does not help.
        self.enroll(course=self.paid_course)
        self.assertEqual(self.client.get(download).status_code, 404)

    def test_paid_course_lessons_need_an_enrollment(self):
        url = self.lesson_url(self.paid_lesson)
        self.client.force_login(self.student)
        self.assertRedirects(self.client.get(url), reverse("courses:detail", args=[self.paid_course.pk]))
        self.assertRedirects(
            self.client.get(reverse("learning:course_learn", args=[self.paid_course.pk])),
            reverse("courses:detail", args=[self.paid_course.pk]),
        )
        # An enrollment record (for example one added by an administrator) opens it.
        self.enroll(course=self.paid_course)
        self.assertContains(self.client.get(url), "Paid notes.")

    def test_draft_lessons_are_hidden_even_when_marked_free_preview(self):
        url = self.lesson_url(self.draft_lesson)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.enroll(course=self.draft_course)
        self.assertEqual(self.client.get(url).status_code, 404)
        other_instructor = User.objects.create_user(email="other-teacher@example.com", password=PASSWORD, role="instructor")
        self.client.force_login(other_instructor)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_instructor_can_preview_own_lessons_without_progress(self):
        self.client.force_login(self.instructor)
        self.assertEqual(self.client.get(self.lesson_url(self.draft_lesson)).status_code, 200)
        self.assertEqual(self.client.get(self.lesson_url(self.private_lesson)).status_code, 200)
        self.assertEqual(LessonProgress.objects.count(), 0)

    def test_opening_a_lesson_records_access_for_enrolled_students_only(self):
        self.client.force_login(self.student)
        self.client.get(self.lesson_url(self.preview_lesson))
        self.assertEqual(LessonProgress.objects.count(), 0)
        self.enroll()
        self.client.get(self.lesson_url(self.preview_lesson))
        progress = LessonProgress.objects.get()
        self.assertEqual((progress.student, progress.lesson, progress.completed_at), (self.student, self.preview_lesson, None))


class LessonCompletionTests(PortalTestCase):
    def complete_url(self, lesson):
        return reverse("learning:lesson_complete", args=[lesson.pk])

    def test_complete_then_undo(self):
        self.enroll()
        self.client.force_login(self.student)
        response = self.client.post(self.complete_url(self.preview_lesson))
        # Completing moves on to the next lesson.
        self.assertRedirects(response, self.lesson_url(self.private_lesson))
        progress = LessonProgress.objects.get(student=self.student, lesson=self.preview_lesson)
        self.assertIsNotNone(progress.completed_at)
        page = self.client.get(self.lesson_url(self.private_lesson))
        self.assertEqual((page.context["done"], page.context["total"], page.context["percent"]), (1, 2, 50))

        self.client.post(self.complete_url(self.preview_lesson))
        progress.refresh_from_db()
        self.assertIsNone(progress.completed_at)

    def test_continue_learning_opens_the_first_unfinished_lesson(self):
        self.enroll()
        self.client.force_login(self.student)
        learn = reverse("learning:course_learn", args=[self.free_course.pk])
        self.assertRedirects(self.client.get(learn), self.lesson_url(self.preview_lesson))
        self.client.post(self.complete_url(self.preview_lesson))
        self.assertRedirects(self.client.get(learn), self.lesson_url(self.private_lesson))

    def test_only_enrolled_students_can_complete_lessons(self):
        url = self.complete_url(self.preview_lesson)
        self.assertRedirects(self.client.post(url), f"{LOGIN_URL}?next={url}")
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.instructor)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(LessonProgress.objects.count(), 0)

    def test_completion_needs_post_and_csrf(self):
        self.enroll()
        url = self.complete_url(self.preview_lesson)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(url).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.student)
        self.assertEqual(strict.post(url).status_code, 403)
        self.assertFalse(LessonProgress.objects.filter(completed_at__isnull=False).exists())

    def test_completion_never_touches_another_students_progress(self):
        self.enroll()
        self.enroll(self.other_student)
        other = LessonProgress.objects.create(student=self.other_student, lesson=self.preview_lesson)
        self.client.force_login(self.student)
        self.client.post(self.complete_url(self.preview_lesson), {"student": self.other_student.pk})
        other.refresh_from_db()
        self.assertIsNone(other.completed_at)
        self.assertEqual(LessonProgress.objects.filter(completed_at__isnull=False).get().student, self.student)


class StudentProfileTests(PortalTestCase):
    PROFILE_URL = reverse("accounts:profile")

    def test_student_can_view_and_update_names(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.PROFILE_URL).status_code, 200)
        response = self.client.post(self.PROFILE_URL, {"first_name": "Sahra", "last_name": "Ali"}, follow=True)
        self.assertContains(response, "Your profile has been saved.")
        self.student.refresh_from_db()
        self.assertEqual(self.student.get_full_name(), "Sahra Ali")

    def test_student_cannot_change_role_login_or_admin_flags(self):
        self.client.force_login(self.student)
        data = {"first_name": "Sahra", "last_name": "Ali", "role": "instructor", "email": "new@example.com",
                "phone": "0615123456", "is_staff": "on", "is_superuser": "on", "headline": "Hacker"}
        self.client.post(self.PROFILE_URL, data)
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, User.Role.STUDENT)
        self.assertEqual((self.student.email, self.student.phone, self.student.headline), ("student@example.com", None, ""))
        self.assertFalse(self.student.is_staff or self.student.is_superuser)

    def test_student_can_change_password_and_stays_logged_in(self):
        self.client.force_login(self.student)
        new_password = "An0ther-Str0ng-Pass!"
        data = {"change_password": "1", "old_password": PASSWORD, "new_password1": new_password, "new_password2": new_password}
        response = self.client.post(self.PROFILE_URL, data, follow=True)
        self.assertContains(response, "Your password has been changed.")
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(new_password))
        self.assertEqual(self.client.get(reverse("learning:dashboard")).status_code, 200)

    def test_password_change_needs_the_current_password_and_a_strong_new_one(self):
        self.client.force_login(self.student)
        wrong_old = {"change_password": "1", "old_password": "wrong", "new_password1": "An0ther-Str0ng-Pass!",
                     "new_password2": "An0ther-Str0ng-Pass!"}
        weak_new = {"change_password": "1", "old_password": PASSWORD, "new_password1": "12345", "new_password2": "12345"}
        for data in [wrong_old, weak_new]:
            response = self.client.post(self.PROFILE_URL, data)
            self.assertTrue(response.context["password_form"].errors)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(PASSWORD))

    def test_profile_requires_login(self):
        self.assertRedirects(self.client.get(self.PROFILE_URL), f"{LOGIN_URL}?next={self.PROFILE_URL}")


class LanguageTests(PortalTestCase):
    def test_pages_are_english_by_default_and_somali_after_switching(self):
        self.assertContains(self.client.get(reverse("core:home")), "Browse courses")
        self.client.post(reverse("set_language"), {"language": "so", "next": "/"})
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "Daalaco koorsooyinka")
        self.assertNotContains(response, "Browse courses")
        self.assertContains(self.client.get(reverse("courses:catalog")), "Raadi")
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        self.assertContains(self.client.get(reverse("core:home")), "Browse courses")


class EnrollmentRoleTests(PortalTestCase):
    """Only ordinary student accounts may use the enrollment endpoint."""

    def try_to_enroll(self, user, course=None):
        course = course or self.free_course
        self.client.force_login(user)
        response = self.client.post(reverse("learning:enroll", args=[course.pk]), follow=True)
        return response, Enrollment.objects.filter(student=user, course=course).exists()

    def assert_refused(self, user):
        response, enrolled = self.try_to_enroll(user)
        self.assertFalse(enrolled)
        self.assertContains(response, "Only student accounts can enroll in courses.")
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_student_can_enroll(self):
        response, enrolled = self.try_to_enroll(self.student)
        self.assertTrue(enrolled)
        self.assertContains(response, "You are enrolled. Enjoy the course!")

    def test_instructor_cannot_enroll(self):
        other_instructor = User.objects.create_user(email="other-teacher@example.com", password=PASSWORD, role="instructor")
        self.assert_refused(other_instructor)
        self.assert_refused(self.instructor)  # nor in a course of their own

    def test_moderator_cannot_enroll(self):
        self.assert_refused(User.objects.create_user(email="mod@example.com", password=PASSWORD, role="moderator"))

    def test_superuser_cannot_enroll(self):
        # A superuser keeps the default "student" role value, and is still refused.
        superuser = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        self.assertEqual(superuser.role, User.Role.STUDENT)
        self.assert_refused(superuser)

    def test_staff_account_cannot_enroll(self):
        self.assert_refused(User.objects.create_user(email="staff@example.com", password=PASSWORD, is_staff=True))

    def test_anonymous_visitor_is_sent_to_login(self):
        url = reverse("learning:enroll", args=[self.free_course.pk])
        self.assertRedirects(self.client.post(url), f"{LOGIN_URL}?next={url}")
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_enroll_button_is_offered_to_students_only(self):
        url = reverse("courses:detail", args=[self.free_course.pk])
        enroll_url = reverse("learning:enroll", args=[self.free_course.pk])
        self.client.force_login(self.student)
        self.assertContains(self.client.get(url), enroll_url)
        others = [
            User.objects.create_user(email="other-teacher@example.com", password=PASSWORD, role="instructor"),
            User.objects.create_user(email="mod@example.com", password=PASSWORD, role="moderator"),
            User.objects.create_superuser(email="admin@example.com", password=PASSWORD),
        ]
        for user in others:
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertNotContains(response, enroll_url)
            self.assertContains(response, "Only student accounts can enroll in courses.")

    def test_enrollment_and_profile_forms_never_change_the_role(self):
        self.client.force_login(self.student)
        extra = {"role": "instructor", "is_staff": "on", "is_superuser": "on", "student": self.other_student.pk}
        self.client.post(reverse("learning:enroll", args=[self.free_course.pk]), extra)
        self.client.post(reverse("accounts:profile"), {"first_name": "A", "last_name": "B", **extra})
        self.client.post(reverse("learning:lesson_complete", args=[self.preview_lesson.pk]), extra)
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, User.Role.STUDENT)
        self.assertFalse(self.student.is_staff or self.student.is_superuser)
        # The enrollment still belongs to the person who posted it.
        self.assertEqual(list(Enrollment.objects.values_list("student", flat=True)), [self.student.pk])

    def test_an_enrollment_cannot_be_created_for_a_non_student_at_all(self):
        other_instructor = User.objects.create_user(email="other-teacher@example.com", password=PASSWORD, role="instructor")
        with self.assertRaises(ValidationError):
            self.enroll(other_instructor)
        self.client.force_login(other_instructor)
        url = self.lesson_url(self.private_lesson)
        self.assertRedirects(self.client.get(url), reverse("courses:detail", args=[self.free_course.pk]))


class SomaliPagesTests(PortalTestCase):
    """The Somali switch reaches the pages added to the translation in this task."""

    def switch(self, language, next_url="/"):
        return self.client.post(reverse("set_language"), {"language": language, "next": next_url})

    def test_switch_keeps_the_current_page_and_its_filters(self):
        page = reverse("courses:catalog") + "?q=alg&level=beginner"
        self.assertRedirects(self.switch("so", page), page)
        self.assertContains(self.client.get(page), "Koorsooyinka la helay")

    def test_switch_ignores_an_outside_address(self):
        response = self.switch("so", "https://evil.example.com/")
        self.assertNotIn("evil.example.com", response.url)

    def test_login_and_registration_pages(self):
        self.switch("so")
        login = self.client.get(LOGIN_URL)
        for text in ["Gal", "Iimayl ama lambarka taleefanka", "Furaha sirta ah", "Muuji furaha sirta ah"]:
            self.assertContains(login, text)
        self.assertNotContains(login, "Email address or phone number")
        register = self.client.get(reverse("accounts:register"))
        for text in ["Samee akoonkaaga", "Cinwaanka iimaylka", "Lambarka taleefanka", "Xaqiiji furaha sirta ah", "ikhtiyaari"]:
            self.assertContains(register, text)

    def test_validation_and_error_messages(self):
        self.switch("so")
        response = self.client.post(LOGIN_URL, {"identifier": "nobody@example.com", "password": "wrong"})
        self.assertContains(response, "Iimaylka, lambarka taleefanka ama furaha sirta ah waa khalad.")
        response = self.client.post(LOGIN_URL, {"identifier": "", "password": ""})
        self.assertContains(response, "Meeshan waa in la buuxiyaa.")
        response = self.client.post(reverse("accounts:register"), {"password1": "abc", "password2": "xyz"})
        self.assertContains(response, "Labada fure ee sirta ah isma laha.")
        response = self.client.post(reverse("accounts:register"), {"password1": PASSWORD, "password2": PASSWORD})
        self.assertContains(response, "Geli cinwaan iimayl ama lambar taleefan.")

    def test_student_profile_and_password_form(self):
        self.client.force_login(self.student)
        self.switch("so")
        page = self.client.get(reverse("accounts:profile"))
        for text in ["Xogtayda", "Magaca koowaad", "Magaca dambe", "Furihii hore ee sirta ah", "Beddel furaha sirta ah"]:
            self.assertContains(page, text)
        response = self.client.post(reverse("accounts:profile"), {"first_name": "Sahra", "last_name": "Ali"}, follow=True)
        self.assertContains(response, "Xogtaada waa la kaydiyay.")
        wrong = {"change_password": "1", "old_password": "wrong", "new_password1": "12345", "new_password2": "12345"}
        response = self.client.post(reverse("accounts:profile"), wrong)
        self.assertContains(response, "Furahaagii hore si khaldan ayaa loo geliyay.")
        self.assertContains(response, "ugu yaraan 8 xaraf")

    def test_instructor_dashboard_and_course_management(self):
        self.client.force_login(self.instructor)
        self.switch("so")
        dashboard = self.client.get(reverse("courses:dashboard"))
        for text in ["Guudmar", "Koorsooyinkayga", "Samee koorso", "Wadarta koorsooyinka", "La daabacay"]:
            self.assertContains(dashboard, text)
        form = self.client.get(reverse("courses:course_create"))
        for text in ["Cinwaan", "Sharraxaad", "Luqadda koorsada", "Qiimaha (USD)", "Yoolalka waxbarashada", "U kaydi qabyo ahaan", "Bilow"]:
            self.assertContains(form, text)
        content = self.client.get(reverse("courses:course_content", args=[self.free_course.pk]))
        for text in ["Nuxurka koorsada", "Ku dar qayb", "Soo geli agab", "Koorsada oo dhan", "Tirtir casharka"]:
            self.assertContains(content, text)
        response = self.client.post(reverse("courses:course_content", args=[self.free_course.pk]), {"title": "Cusub"}, follow=True)
        self.assertContains(response, "Qaybta waa lagu daray.")

    def test_english_is_unchanged_after_switching_back(self):
        self.switch("so")
        self.switch("en")
        self.assertContains(self.client.get(LOGIN_URL), "Email address or phone number")
        self.client.force_login(self.instructor)
        self.assertContains(self.client.get(reverse("courses:dashboard")), "Total courses")


class PaidCourseTests(PortalTestCase):
    """Paid courses show their price and cannot be opened without an authorized enrollment."""

    def setUp(self):
        self.detail_url = reverse("courses:detail", args=[self.paid_course.pk])
        self.enroll_url = reverse("learning:enroll", args=[self.paid_course.pk])

    def test_price_and_labels_on_public_pages(self):
        for url in [reverse("core:home"), reverse("courses:catalog"), self.detail_url]:
            response = self.client.get(url)
            self.assertContains(response, "$25.00")
            self.assertContains(response, "USD")
            self.assertContains(response, ">Paid<")
        free_page = self.client.get(reverse("courses:detail", args=[self.free_course.pk]))
        self.assertContains(free_page, ">Free<")
        self.assertNotContains(free_page, ">Paid<")
        self.assertNotContains(free_page, "$")

    def test_price_on_student_and_instructor_pages(self):
        self.enroll(course=self.paid_course)
        self.client.force_login(self.student)
        self.assertContains(self.client.get(self.detail_url), "$25.00")
        self.client.force_login(self.instructor)
        pages = [
            reverse("courses:dashboard"),
            reverse("courses:course_list"),
            reverse("courses:course_detail", args=[self.paid_course.pk]),
        ]
        for url in pages:
            response = self.client.get(url)
            self.assertContains(response, "$25.00")
            self.assertContains(response, ">Paid<")
            self.assertContains(response, ">Free<" if url != pages[2] else "USD")

    @override_settings(CURRENCY_CODE="SOS", CURRENCY_SYMBOL="Sh ")
    def test_configured_currency_is_used_everywhere(self):
        self.client.force_login(self.instructor)
        urls = [
            reverse("core:home"), reverse("courses:catalog"), self.detail_url,
            reverse("courses:dashboard"), reverse("courses:course_list"),
            reverse("courses:course_detail", args=[self.paid_course.pk]),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertContains(response, "Sh 25.00")
            self.assertContains(response, "SOS")
            self.assertNotContains(response, "$")
            self.assertNotContains(response, "USD")
        self.assertContains(self.client.get(reverse("courses:course_create")), "Price (SOS)")

    def test_paid_course_page_offers_no_way_to_enroll(self):
        visitors = [None, self.student, User.objects.create_user(email="mod@example.com", password=PASSWORD, role="moderator")]
        for user in visitors:
            if user:
                self.client.force_login(user)
            response = self.client.get(self.detail_url)
            self.assertContains(response, "Payment Coming Soon")
            self.assertContains(response, 'disabled aria-disabled="true"')
            self.assertContains(response, "Online payment is not available yet.")
            self.assertNotContains(response, self.enroll_url)
            self.assertNotContains(response, "Enroll for free")

    def test_request_parameters_cannot_make_a_paid_course_free(self):
        self.client.force_login(self.student)
        tricks = {"price": "0", "is_free": "1", "free": "true", "paid": "1", "status": "paid", "course": self.free_course.pk}
        self.client.post(self.enroll_url, tricks)
        self.client.post(self.enroll_url + "?price=0&paid=1&is_free=1", tricks)
        self.assertEqual(self.client.get(self.enroll_url + "?price=0").status_code, 405)
        self.assertEqual(Enrollment.objects.count(), 0)
        self.paid_course.refresh_from_db()
        self.assertEqual(str(self.paid_course.price), "25.00")
        # Nothing was opened either.
        self.assertRedirects(self.client.get(self.lesson_url(self.paid_lesson)), self.detail_url)

    def test_no_role_can_enroll_in_a_paid_course(self):
        users = [
            self.student,
            self.instructor,
            User.objects.create_user(email="mod@example.com", password=PASSWORD, role="moderator"),
            User.objects.create_user(email="staff@example.com", password=PASSWORD, is_staff=True),
            User.objects.create_superuser(email="admin@example.com", password=PASSWORD),
        ]
        for user in users:
            self.client.force_login(user)
            self.client.post(self.enroll_url, {"price": "0"})
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_only_an_enrollment_opens_paid_lessons(self):
        lesson_url = self.lesson_url(self.paid_lesson)
        self.assertRedirects(self.client.get(lesson_url), f"{LOGIN_URL}?next={lesson_url}")
        moderator = User.objects.create_user(email="mod@example.com", password=PASSWORD, role="moderator")
        other_instructor = User.objects.create_user(email="other-teacher@example.com", password=PASSWORD, role="instructor")
        for user in [self.student, self.other_student, moderator, other_instructor]:
            self.client.force_login(user)
            self.assertRedirects(self.client.get(lesson_url), self.detail_url)
        # An authorized enrollment opens the course for that student only.
        self.enroll(course=self.paid_course)
        self.client.force_login(self.student)
        self.assertContains(self.client.get(lesson_url), "Paid notes.")
        self.assertContains(self.client.get(self.detail_url), "Continue learning")
        self.client.force_login(self.other_student)
        self.assertRedirects(self.client.get(lesson_url), self.detail_url)

    def test_somali_paid_course_page(self):
        self.client.post(reverse("set_language"), {"language": "so", "next": "/"})
        response = self.client.get(self.detail_url)
        for text in ["Lacag bixintu waa soo socotaa", "Lacag leh", "Lacag bixinta onlaynka ah weli lama heli karo.", "$25.00"]:
            self.assertContains(response, text)
        self.assertNotContains(response, "Payment Coming Soon")


class EnrollmentAdminTests(PortalTestCase):
    """In Django Admin only a superuser can hand out course access."""

    add_url = reverse("admin:learning_enrollment_add")

    def setUp(self):
        self.staff = User.objects.create_user(email="staff@example.com", password=PASSWORD, is_staff=True)
        # Even with every enrollment permission, ordinary staff cannot add, change or delete.
        self.staff.user_permissions.set(Permission.objects.filter(content_type__app_label="learning"))
        self.superuser = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)

    def test_staff_cannot_add_change_or_delete_enrollments(self):
        enrollment = self.enroll()
        self.client.force_login(self.staff)
        data = {"student": self.other_student.pk, "course": self.paid_course.pk}
        self.assertEqual(self.client.post(self.add_url, data).status_code, 403)
        change_url = reverse("admin:learning_enrollment_change", args=[enrollment.pk])
        self.assertEqual(self.client.post(change_url, data).status_code, 403)
        delete_url = reverse("admin:learning_enrollment_delete", args=[enrollment.pk])
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        self.assertEqual(list(Enrollment.objects.values_list("student", "course")), [(self.student.pk, self.free_course.pk)])
        # Looking at the list is still allowed.
        self.assertEqual(self.client.get(reverse("admin:learning_enrollment_changelist")).status_code, 200)

    def test_superuser_can_enroll_a_student_in_a_paid_course(self):
        self.client.force_login(self.superuser)
        # Extra fields are ignored: the grant is always recorded as manual, by the person logged in.
        data = {"student": self.student.pk, "course": self.paid_course.pk, "source": "free", "granted_by": self.owner.pk}
        self.client.post(self.add_url, data)
        enrollment = Enrollment.objects.get(student=self.student, course=self.paid_course)
        self.assertEqual((enrollment.source, enrollment.granted_by), (Enrollment.Source.MANUAL, self.superuser))
        self.assertFalse(Payment.objects.exists())  # a manual grant is not a payment
        self.assertContains(self.client.get(reverse("admin:learning_enrollment_changelist")), "Granted by an administrator")
        # Once granted it can be removed, but not edited.
        change_url = reverse("admin:learning_enrollment_change", args=[enrollment.pk])
        self.client.post(change_url, {"student": self.other_student.pk, "course": self.paid_course.pk})
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.student, self.student)
        self.client.force_login(self.student)
        self.assertContains(self.client.get(self.lesson_url(self.paid_lesson)), "Paid notes.")

    def test_admin_refuses_to_enroll_an_account_that_is_not_a_student(self):
        self.client.force_login(self.superuser)
        for user in [self.instructor, self.staff, self.superuser]:
            response = self.client.post(self.add_url, {"student": user.pk, "course": self.paid_course.pk})
            self.assertContains(response, "Only student accounts can enroll in courses.")
        self.assertEqual(Enrollment.objects.count(), 0)


class EnrollmentRuleTests(PortalTestCase):
    """The rules hold however an enrollment is created, not only through the enroll page."""

    def assert_refused(self, **fields):
        fields.setdefault("student", self.student)
        fields.setdefault("course", self.paid_course)
        attempts = [
            lambda: Enrollment.objects.create(**fields),
            lambda: Enrollment(**fields).save(),
            lambda: Enrollment.objects.get_or_create(**fields),
            lambda: Enrollment.objects.update_or_create(student=fields["student"], course=fields["course"], defaults=fields),
            lambda: Enrollment(**fields).full_clean(),
        ]
        for attempt in attempts:
            with self.assertRaises(ValidationError):
                attempt()
        related = {key: value for key, value in fields.items() if key != "student"}
        with self.assertRaises(ValidationError):
            fields["student"].enrollments.create(**related)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_the_enroll_page_records_a_free_enrollment(self):
        self.client.force_login(self.student)
        self.client.post(reverse("learning:enroll", args=[self.free_course.pk]))
        enrollment = Enrollment.objects.get()
        self.assertEqual((enrollment.source, enrollment.granted_by), (Enrollment.Source.FREE, None))

    def test_free_course_can_be_joined_directly_by_a_student(self):
        Enrollment.objects.create(student=self.student, course=self.free_course)
        self.assertEqual(Enrollment.objects.get().source, Enrollment.Source.FREE)

    def test_paid_course_cannot_be_joined_as_a_free_enrollment(self):
        self.assert_refused()
        self.assert_refused(source=Enrollment.Source.FREE)

    def test_a_course_that_was_given_a_price_is_closed_to_new_free_enrollments(self):
        self.enroll()  # joined while the course was free
        Course.objects.filter(pk=self.free_course.pk).update(price="5.00")
        self.free_course.refresh_from_db()
        with self.assertRaises(ValidationError):
            Enrollment.objects.create(student=self.other_student, course=self.free_course)
        # The student who joined while it was free keeps access, and can be saved again.
        self.client.force_login(self.student)
        detail = reverse("courses:detail", args=[self.free_course.pk])
        self.assertEqual(self.client.get(self.lesson_url(self.private_lesson)).status_code, 200)
        self.assertContains(self.client.get(detail), "Continue learning")
        Enrollment.objects.get().save()
        # Everyone else sees a paid course.
        self.client.force_login(self.other_student)
        self.assertRedirects(self.client.get(self.lesson_url(self.private_lesson)), detail, fetch_redirect_response=False)
        self.assertContains(self.client.get(detail), "Payment Coming Soon")

    def test_accounts_that_are_not_students_are_refused_for_every_source(self):
        others = [
            self.instructor,
            self.owner,
            User.objects.create_user(email="mod@example.com", password=PASSWORD, role="moderator"),
            User.objects.create_user(email="staff@example.com", password=PASSWORD, is_staff=True),
        ]
        for user in others:
            self.assert_refused(student=user, course=self.free_course)
            self.assert_refused(student=user, source=Enrollment.Source.MANUAL, granted_by=self.owner)

    def test_manual_grant_needs_a_superuser(self):
        staff = User.objects.create_user(email="staff@example.com", password=PASSWORD, is_staff=True)
        self.assert_refused(source=Enrollment.Source.MANUAL)
        for user in [staff, self.instructor, self.student, self.other_student]:
            self.assert_refused(source=Enrollment.Source.MANUAL, granted_by=user)
        enrollment = self.enroll(course=self.paid_course)
        self.assertEqual((enrollment.source, enrollment.granted_by), (Enrollment.Source.MANUAL, self.owner))

    def test_free_enrollment_cannot_name_a_granter_and_unknown_sources_are_refused(self):
        self.assert_refused(course=self.free_course, granted_by=self.owner)
        with self.assertRaises(ValidationError):
            Enrollment(student=self.student, course=self.free_course, source="payment").full_clean()

    def test_database_refuses_a_manual_enrollment_without_a_name_even_in_bulk(self):
        # bulk_create skips save(), so the database constraint is the last line of defence here.
        row = Enrollment(student=self.student, course=self.paid_course, source=Enrollment.Source.MANUAL)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.bulk_create([row])
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_a_paid_payment_record_does_not_create_or_replace_an_enrollment(self):
        Payment.objects.create(student=self.student, course=self.paid_course, amount="25.00", currency="USD", status="paid")
        self.assertEqual(Enrollment.objects.count(), 0)
        self.assert_refused()  # still no free way in
        self.client.force_login(self.student)
        detail = reverse("courses:detail", args=[self.paid_course.pk])
        self.assertRedirects(self.client.get(self.lesson_url(self.paid_lesson)), detail)
        self.assertContains(self.client.get(detail), "Payment Coming Soon")


class AccessTestCase(PortalTestCase):
    """Helpers that check every student page of one course at once."""

    def assert_closed(self, user, lesson):
        """No lesson, no material, no completion, and not listed on the dashboard."""
        course = lesson.section.course
        self.client.force_login(user)
        detail = reverse("courses:detail", args=[course.pk])
        self.assertRedirects(self.client.get(self.lesson_url(lesson)), detail, fetch_redirect_response=False)
        self.assertRedirects(
            self.client.get(reverse("learning:course_learn", args=[course.pk])), detail, fetch_redirect_response=False
        )
        self.assertEqual(self.client.post(reverse("learning:lesson_complete", args=[lesson.pk])).status_code, 404)
        self.assertNotContains(self.client.get(detail), "Continue learning")
        for name in ["learning:dashboard", "learning:my_courses"]:
            listed = [enrollment.course for enrollment in self.client.get(reverse(name)).context["enrollments"]]
            self.assertNotIn(course, listed)
        recent = self.client.get(reverse("learning:dashboard")).context["recent_lessons"]
        self.assertNotIn(course, [progress.lesson.section.course for progress in recent])
        if course == self.free_course:
            download = reverse("courses:material_download", args=[self.material.pk])
            self.assertEqual(self.client.get(download).status_code, 404)

    def assert_open(self, user, lesson):
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.lesson_url(lesson)).status_code, 200)
        titles = [e.course for e in self.client.get(reverse("learning:my_courses")).context["enrollments"]]
        self.assertIn(lesson.section.course, titles)


class AccessBypassTests(AccessTestCase):
    """Rows written past save() are refused by the database or simply open nothing."""

    def raw_insert(self, student, course, source="free", granted_by=None):
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO learning_enrollment (student_id, course_id, source, granted_by_id, enrolled_at) "
                "VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)",
                [student.pk, course.pk, source, granted_by and granted_by.pk],
            )

    def test_bulk_create_of_a_free_row_does_not_open_a_paid_course(self):
        Enrollment.objects.bulk_create([Enrollment(student=self.student, course=self.paid_course)])
        self.assertEqual(Enrollment.objects.count(), 1)
        self.assert_closed(self.student, self.paid_lesson)
        self.assertContains(self.client.get(reverse("courses:detail", args=[self.paid_course.pk])), "Payment Coming Soon")

    def test_queryset_update_cannot_move_a_free_enrollment_to_a_paid_course(self):
        self.enroll()
        # A real free enrollment is tied to its course by the database.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.update(course=self.paid_course)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.update(joined_free_course=self.paid_course)
        # A row that never went through save() can be moved, but opens nothing.
        Enrollment.objects.bulk_create([Enrollment(student=self.other_student, course=self.free_course)])
        Enrollment.objects.filter(student=self.other_student).update(course=self.paid_course)
        self.assert_closed(self.other_student, self.paid_lesson)

    def test_only_a_saved_free_enrollment_survives_a_price_being_added(self):
        self.enroll()  # through save()
        Enrollment.objects.bulk_create([Enrollment(student=self.other_student, course=self.free_course)])
        self.raw_insert(User.objects.create_user(email="third@example.com", password=PASSWORD), self.free_course)
        self.assertEqual(Enrollment.objects.filter(joined_free_course__isnull=False).count(), 1)
        Course.objects.filter(pk=self.free_course.pk).update(price="12.00")
        self.assert_open(self.student, self.private_lesson)
        self.assert_closed(self.other_student, self.private_lesson)
        self.assert_closed(User.objects.get(email="third@example.com"), self.private_lesson)

    def test_joined_free_is_not_recorded_for_manual_grants_or_paid_courses(self):
        grant = self.enroll(course=self.paid_course)
        self.assertIsNone(grant.joined_free_course)
        # Passing the field in does not help: save() decides it, the caller does not.
        for claimed in [self.free_course, self.paid_course]:
            with self.assertRaises(ValidationError):
                Enrollment.objects.create(student=self.other_student, course=self.paid_course, joined_free_course=claimed)
        # Nor does setting it on a row that slipped in and then saving that row.
        Enrollment.objects.bulk_create([Enrollment(student=self.other_student, course=self.paid_course)])
        slipped = Enrollment.objects.get(student=self.other_student)
        slipped.joined_free_course = self.paid_course
        with self.assertRaises(ValidationError):
            slipped.save()
        self.assert_closed(self.other_student, self.paid_lesson)
        Enrollment.objects.filter(pk=slipped.pk).delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.bulk_create(
                [Enrollment(student=self.other_student, course=self.paid_course, joined_free_course=self.free_course)]
            )

    def test_queryset_update_cannot_turn_a_row_into_a_manual_grant_without_a_name(self):
        self.enroll()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.update(source=Enrollment.Source.MANUAL)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.update(source="payment")
        self.assertEqual(Enrollment.objects.get().source, Enrollment.Source.FREE)

    def test_update_or_create_and_resaving_are_checked_like_a_new_enrollment(self):
        enrollment = self.enroll()
        with self.assertRaises(ValidationError):
            Enrollment.objects.update_or_create(student=self.student, defaults={"course": self.paid_course})
        enrollment.course = self.paid_course
        with self.assertRaises(ValidationError):
            enrollment.save()
        enrollment.refresh_from_db()
        enrollment.student = self.instructor
        with self.assertRaises(ValidationError):
            enrollment.save()
        self.assertEqual(list(Enrollment.objects.values_list("student", "course")), [(self.student.pk, self.free_course.pk)])

    def test_raw_sql_free_row_does_not_open_a_paid_course(self):
        self.raw_insert(self.student, self.paid_course)
        self.assert_closed(self.student, self.paid_lesson)

    def test_raw_sql_cannot_write_a_nameless_grant_or_an_unknown_source(self):
        for source, granted_by in [("manual", None), ("payment", None), ("payment", self.owner), ("free", self.owner)]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.raw_insert(self.student, self.paid_course, source, granted_by)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_rows_written_for_accounts_that_are_not_students_open_nothing(self):
        moderator = User.objects.create_user(email="mod@example.com", password=PASSWORD, role="moderator")
        staff = User.objects.create_user(email="staff@example.com", password=PASSWORD, is_staff=True)
        others = [moderator, staff, self.owner]
        Enrollment.objects.bulk_create([Enrollment(student=user, course=self.free_course) for user in others])
        for user in others:
            self.raw_insert(user, self.paid_course, "manual", self.owner)
            self.assert_closed(user, self.private_lesson)
            self.assert_closed(user, self.paid_lesson)

    def test_a_payment_record_changes_nothing_for_a_bypassed_row(self):
        Payment.objects.create(student=self.student, course=self.paid_course, amount="25.00", currency="USD", status="paid")
        Enrollment.objects.bulk_create([Enrollment(student=self.student, course=self.paid_course)])
        self.assert_closed(self.student, self.paid_lesson)


class SuperuserAccessTests(AccessTestCase):
    """Administrator rights are not student rights."""

    def test_superuser_has_no_student_access_to_lessons_or_materials(self):
        self.assert_closed(self.owner, self.private_lesson)
        self.assert_closed(self.owner, self.paid_lesson)
        # Draft courses stay hidden as for everyone else.
        self.assertEqual(self.client.get(self.lesson_url(self.draft_lesson)).status_code, 404)

    def test_superuser_keeps_administration_and_public_pages(self):
        self.client.force_login(self.owner)
        for name in ["admin:index", "admin:learning_enrollment_changelist", "admin:courses_course_changelist",
                     "admin:payments_payment_changelist", "admin:accounts_user_changelist"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        # Free previews are public, so they open for a superuser like for any visitor.
        response = self.client.get(self.lesson_url(self.preview_lesson))
        self.assertContains(response, "Preview notes for everyone.")
        self.assertFalse(LessonProgress.objects.exists())

    def test_superuser_who_teaches_a_course_previews_it_as_its_instructor(self):
        own = make_course(self.owner, self.category, "Owner course", price="10.00")
        own_lesson = Lesson.objects.create(section=Section.objects.create(course=own, title="S", order=1), title="L", order=1)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.lesson_url(own_lesson)).status_code, 200)


class RoleChangeTests(AccessTestCase):
    """Enrollments are kept through a role change, but only open courses for Student accounts."""

    changes = [
        {"role": "instructor"},
        {"role": "moderator"},
        {"is_staff": True},
        {"is_superuser": True, "is_staff": True},
    ]

    def setUp(self):
        self.enroll()
        self.enroll(course=self.paid_course)
        self.client.force_login(self.student)
        self.client.post(reverse("learning:lesson_complete", args=[self.private_lesson.pk]))

    def change(self, **fields):
        User.objects.filter(pk=self.student.pk).update(**fields)
        self.student.refresh_from_db()

    def test_access_stops_while_the_account_is_not_a_student_and_returns_afterwards(self):
        back_to_student = {"role": "student", "is_staff": False, "is_superuser": False}
        for fields in self.changes:
            self.change(**fields)
            self.assert_closed(self.student, self.private_lesson)
            self.assert_closed(self.student, self.paid_lesson)
            # Nothing was deleted.
            self.assertEqual(Enrollment.objects.filter(student=self.student).count(), 2)
            self.assertEqual(LessonProgress.objects.filter(student=self.student, completed_at__isnull=False).count(), 1)

            self.change(**back_to_student)
            self.assert_open(self.student, self.private_lesson)
            self.assert_open(self.student, self.paid_lesson)
            enrollments = self.client.get(reverse("learning:my_courses")).context["enrollments"]
            self.assertEqual(sorted(e.done for e in enrollments), [0, 1])  # earlier progress is back

    def test_approved_instructor_application_keeps_records_but_closes_student_access(self):
        self.change(role="instructor")
        own = make_course(self.student, self.category, "Their own course")
        own_lesson = Lesson.objects.create(section=Section.objects.create(course=own, title="S", order=1), title="L", order=1)
        self.assert_closed(self.student, self.paid_lesson)
        self.assertEqual(self.client.get(self.lesson_url(own_lesson)).status_code, 200)  # their own course
        with self.assertRaises(ValidationError):
            Enrollment.objects.create(student=self.student, course=self.draft_course)

    def test_returning_student_follows_the_current_rules(self):
        self.change(role="instructor")
        Course.objects.filter(pk=self.free_course.pk).update(price="9.00")
        self.change(role="student")
        # They joined the first course while it was free, so both courses open again.
        self.assert_open(self.student, self.private_lesson)
        self.assert_open(self.student, self.paid_lesson)
        response = self.client.post(reverse("learning:enroll", args=[self.free_course.pk]), follow=True)
        self.assertContains(response, "This course is not free.")
