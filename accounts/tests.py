from unittest import mock

from django.contrib.auth.models import Permission
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from .models import InstructorApplication, User, normalize_phone

PASSWORD = "Str0ng-Passw0rd!"
REGISTER_URL = reverse("accounts:register")
LOGIN_URL = reverse("accounts:login")
LOGOUT_URL = reverse("accounts:logout")
DASHBOARD_URL = reverse("learning:dashboard")
APPLICATION_URL = reverse("accounts:instructor_application")
ADMIN_APPLICATIONS_URL = reverse("admin:accounts_instructorapplication_changelist")
APPLICATION_DATA = {
    "full_name": "Amina Ali",
    "expertise": "Mathematics teacher",
    "biography": "Ten years of teaching.",
    "teaching_experience": "Secondary school and private tutoring.",
    "reason": "To reach more students.",
}
# The fields the admin's user form needs besides the email or phone.
USER_ADMIN_FORM = {"role": "student", "is_active": "on", "date_joined_0": "2026-01-01", "date_joined_1": "10:00:00"}
LOGIN_ERROR = "Incorrect email address, phone number or password."


class RegistrationTests(TestCase):
    def register(self, **data):
        data.setdefault("password1", PASSWORD)
        data.setdefault("password2", PASSWORD)
        return self.client.post(REGISTER_URL, data)

    def test_register_with_email_only(self):
        response = self.register(email="Amina@Example.com")
        self.assertRedirects(response, DASHBOARD_URL)
        user = User.objects.get()
        self.assertEqual(user.email, "amina@example.com")
        self.assertIsNone(user.phone)
        # Logged in automatically, and the password is stored hashed.
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_register_with_phone_only(self):
        response = self.register(phone="061 512 3456")
        self.assertRedirects(response, DASHBOARD_URL)
        user = User.objects.get()
        self.assertEqual(user.phone, "+252615123456")
        self.assertIsNone(user.email)

    def test_register_with_email_and_phone(self):
        response = self.register(email="both@example.com", phone="+252615123456")
        self.assertRedirects(response, DASHBOARD_URL)
        user = User.objects.get()
        self.assertEqual((user.email, user.phone), ("both@example.com", "+252615123456"))

    def test_two_phone_only_users_can_register(self):
        self.register(phone="0615123456")
        self.client.logout()
        self.register(phone="0615123457")
        self.assertEqual(User.objects.count(), 2)

    def test_register_without_email_or_phone(self):
        response = self.register()
        self.assertContains(response, "Enter an email address or a phone number.")
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(email="taken@example.com", password=PASSWORD)
        response = self.register(email="TAKEN@example.com")
        self.assertContains(response, "User with this Email already exists.")
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_phone_is_rejected(self):
        User.objects.create_user(phone="+252615123456", password=PASSWORD)
        response = self.register(phone="0615123456")
        self.assertContains(response, "User with this Phone already exists.")
        self.assertEqual(User.objects.count(), 1)

    def test_password_mismatch(self):
        response = self.register(email="a@example.com", password2="Different-Pass1!")
        self.assertContains(response, "The two passwords do not match.")
        self.assertEqual(User.objects.count(), 0)

    def test_weak_password_is_rejected(self):
        response = self.register(email="a@example.com", password1="12345", password2="12345")
        self.assertContains(response, "This password is too short.")
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_email(self):
        response = self.register(email="not-an-email")
        self.assertContains(response, "Enter a valid email address.")
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_phone(self):
        response = self.register(phone="abc123")
        self.assertContains(response, "Enter a valid phone number.")
        self.assertEqual(User.objects.count(), 0)


class LoginLogoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.email_user = User.objects.create_user(email="amina@example.com", password=PASSWORD)
        cls.phone_user = User.objects.create_user(phone="+252615123456", password=PASSWORD)

    def login(self, identifier, password=PASSWORD):
        return self.client.post(LOGIN_URL, {"identifier": identifier, "password": password})

    def test_login_with_email(self):
        response = self.login("Amina@Example.com")
        self.assertRedirects(response, DASHBOARD_URL)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.email_user.pk)

    def test_login_with_phone(self):
        response = self.login("0615123456")
        self.assertRedirects(response, DASHBOARD_URL)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.phone_user.pk)

    def test_incorrect_password(self):
        response = self.login("amina@example.com", "wrong-password")
        self.assertContains(response, LOGIN_ERROR)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unknown_account_gets_the_same_error(self):
        for identifier in ["nobody@example.com", "0619999999"]:
            response = self.login(identifier)
            self.assertContains(response, LOGIN_ERROR)

    def test_inactive_user_cannot_log_in(self):
        User.objects.filter(pk=self.email_user.pk).update(is_active=False)
        response = self.login("amina@example.com")
        self.assertContains(response, LOGIN_ERROR)

    def test_login_follows_safe_next_only(self):
        response = self.client.post(
            LOGIN_URL + "?next=https://evil.example.com/",
            {"identifier": "amina@example.com", "password": PASSWORD},
        )
        self.assertRedirects(response, DASHBOARD_URL)

    def test_logout(self):
        self.client.force_login(self.email_user)
        response = self.client.post(LOGOUT_URL, follow=True)
        self.assertRedirects(response, reverse("core:home"))
        self.assertContains(response, "You have been logged out.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        self.client.force_login(self.email_user)
        response = self.client.get(LOGOUT_URL)
        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_csrf_protection(self):
        client = Client(enforce_csrf_checks=True)
        login_data = {"identifier": "amina@example.com", "password": PASSWORD}
        register_data = {"email": "new@example.com", "password1": PASSWORD, "password2": PASSWORD}
        self.assertEqual(client.post(LOGIN_URL, login_data).status_code, 403)
        self.assertEqual(client.post(REGISTER_URL, register_data).status_code, 403)
        client.force_login(self.email_user)
        self.assertEqual(client.post(LOGOUT_URL).status_code, 403)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_protected_page_redirects_to_login_when_logged_out(self):
        response = self.client.get(DASHBOARD_URL)
        self.assertRedirects(response, f"{LOGIN_URL}?next={DASHBOARD_URL}")


class AdminTests(TestCase):
    def test_admin_can_add_and_edit_users(self):
        admin_user = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        self.client.force_login(admin_user)
        response = self.client.post(
            reverse("admin:accounts_user_add"),
            {"phone": "0615123456", "usable_password": "true", "password1": PASSWORD, "password2": PASSWORD},
        )
        new_user = User.objects.get(phone="+252615123456")
        self.assertRedirects(response, reverse("admin:accounts_user_change", args=[new_user.pk]))
        self.assertEqual(self.client.get(reverse("admin:accounts_user_changelist")).status_code, 200)


class PhoneNormalizationTests(TestCase):
    """Local and international spellings of a number must be one account."""

    SAME_NUMBER = ["0615123456", "615123456", "+252615123456", "00252615123456", "+252 61 512-3456"]

    def test_all_spellings_normalize_to_one_value(self):
        for spelling in self.SAME_NUMBER:
            self.assertEqual(normalize_phone(spelling), "+252615123456")

    def test_register_local_then_login_with_any_spelling(self):
        data = {"phone": "0615123456", "password1": PASSWORD, "password2": PASSWORD}
        self.client.post(REGISTER_URL, data)
        user = User.objects.get()
        self.assertEqual(user.phone, "+252615123456")
        for spelling in self.SAME_NUMBER:
            self.client.logout()
            response = self.client.post(LOGIN_URL, {"identifier": spelling, "password": PASSWORD})
            self.assertRedirects(response, DASHBOARD_URL)
            self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_register_international_then_login_local(self):
        data = {"phone": "+252615123456", "password1": PASSWORD, "password2": PASSWORD}
        self.client.post(REGISTER_URL, data)
        response = self.client.post(LOGIN_URL, {"identifier": "0615123456", "password": PASSWORD})
        self.assertRedirects(response, DASHBOARD_URL)

    def test_other_spelling_of_registered_number_is_a_duplicate(self):
        User.objects.create_user(phone="0615123456", password=PASSWORD)
        for spelling in self.SAME_NUMBER:
            data = {"phone": spelling, "password1": PASSWORD, "password2": PASSWORD}
            response = self.client.post(REGISTER_URL, data)
            self.assertContains(response, "User with this Phone already exists.")
        self.assertEqual(User.objects.count(), 1)


class CreateSuperuserTests(TestCase):
    def create_superuser(self, email, phone):
        """Run the interactive createsuperuser command with typed answers."""
        answers = {"Email": email, "Phone": phone}

        def typed_answer(prompt):
            return next(answer for label, answer in answers.items() if prompt.startswith(label))

        stdin = mock.Mock()
        stdin.isatty.return_value = True
        with mock.patch("builtins.input", typed_answer), mock.patch("getpass.getpass", return_value=PASSWORD):
            call_command("createsuperuser", stdin=stdin, stdout=mock.Mock())

    def test_superuser_with_phone_only(self):
        self.create_superuser(email="", phone="0615123456")
        user = User.objects.get()
        self.assertIsNone(user.email)
        self.assertEqual(user.phone, "+252615123456")
        self.assertTrue(user.is_staff and user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))

    def test_superuser_with_email_only(self):
        self.create_superuser(email="Admin@Example.com", phone="")
        user = User.objects.get()
        self.assertEqual(user.email, "admin@example.com")
        self.assertIsNone(user.phone)
        self.assertTrue(user.is_staff and user.is_superuser)

    def test_superuser_with_email_and_phone(self):
        self.create_superuser(email="admin@example.com", phone="+252615123456")
        user = User.objects.get()
        self.assertEqual((user.email, user.phone), ("admin@example.com", "+252615123456"))

    def test_superuser_needs_email_or_phone(self):
        with self.assertRaisesMessage(CommandError, "Enter an email address or a phone number."):
            self.create_superuser(email="", phone="")
        self.assertEqual(User.objects.count(), 0)

    def test_phone_superuser_can_log_in_to_admin(self):
        self.create_superuser(email="", phone="0615123456")
        self.client.post(LOGIN_URL, {"identifier": "+252615123456", "password": PASSWORD})
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)


class RoleTests(TestCase):
    def test_new_user_is_a_student(self):
        self.client.post(REGISTER_URL, {"email": "new@example.com", "password1": PASSWORD, "password2": PASSWORD})
        self.assertEqual(User.objects.get().role, User.Role.STUDENT)

    def test_user_cannot_choose_a_role_or_admin_flags_when_registering(self):
        data = {"email": "new@example.com", "password1": PASSWORD, "password2": PASSWORD}
        data.update({"role": "instructor", "is_staff": "on", "is_superuser": "on"})
        self.client.post(REGISTER_URL, data)
        user = User.objects.get()
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_student_cannot_change_own_role(self):
        student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        self.client.force_login(student)
        # The application form ignores role fields, and the user admin is closed to students.
        self.client.post(APPLICATION_URL, {**APPLICATION_DATA, "role": "instructor", "status": "approved"})
        response = self.client.post(
            reverse("admin:accounts_user_change", args=[student.pk]), {"role": "instructor"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)
        student.refresh_from_db()
        self.assertEqual(student.role, User.Role.STUDENT)
        self.assertEqual(student.instructor_applications.get().status, "pending")


class InstructorApplicationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(email="student@example.com", password=PASSWORD)

    def apply(self, user=None):
        self.client.force_login(user or self.student)
        return self.client.post(APPLICATION_URL, APPLICATION_DATA, follow=True)

    def test_student_can_submit_application(self):
        response = self.apply()
        application = InstructorApplication.objects.get()
        self.assertEqual(application.user, self.student)
        self.assertEqual(application.status, InstructorApplication.Status.PENDING)
        self.assertIsNone(application.reviewed_by)
        # Confirmation message and status display.
        self.assertContains(response, "Your application has been submitted.")
        self.assertContains(response, "Pending")
        self.assertNotContains(response, "Submit application")

    def test_anonymous_user_cannot_apply(self):
        response = self.client.post(APPLICATION_URL, APPLICATION_DATA)
        self.assertRedirects(response, f"{LOGIN_URL}?next={APPLICATION_URL}")
        self.assertEqual(InstructorApplication.objects.count(), 0)

    def test_required_fields_are_validated(self):
        self.client.force_login(self.student)
        response = self.client.post(APPLICATION_URL, {"full_name": "Amina Ali"})
        self.assertContains(response, "This field is required.")
        self.assertEqual(InstructorApplication.objects.count(), 0)

    def test_duplicate_pending_application_is_prevented(self):
        self.apply()
        response = self.apply()
        self.assertContains(response, "You cannot submit an instructor application.")
        self.assertEqual(InstructorApplication.objects.count(), 1)
        # The database refuses a second pending application as well.
        with self.assertRaises(IntegrityError), transaction.atomic():
            InstructorApplication.objects.create(user=self.student, **APPLICATION_DATA)

    def test_instructor_cannot_apply(self):
        instructor = User.objects.create_user(email="teacher@example.com", password=PASSWORD, role="instructor")
        response = self.apply(instructor)
        self.assertContains(response, "You cannot submit an instructor application.")
        self.assertEqual(InstructorApplication.objects.count(), 0)

    def test_moderator_and_administrators_cannot_apply(self):
        moderator = User.objects.create_user(email="mod@example.com", password=PASSWORD, role="moderator")
        staff = User.objects.create_user(email="staff@example.com", password=PASSWORD, is_staff=True)
        superuser = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        for user in [moderator, staff, superuser]:
            self.apply(user)
        self.assertEqual(InstructorApplication.objects.count(), 0)

    def test_user_sees_only_own_application(self):
        self.apply()
        other = User.objects.create_user(email="other@example.com", password=PASSWORD)
        self.client.force_login(other)
        response = self.client.get(APPLICATION_URL)
        self.assertNotContains(response, "Your application")
        self.assertContains(response, "Submit application")

    def test_rejected_student_sees_status_and_can_apply_again(self):
        admin_user = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        InstructorApplication.objects.create(user=self.student, **APPLICATION_DATA).review(admin_user, approved=False)
        self.client.force_login(self.student)
        self.assertContains(self.client.get(APPLICATION_URL), "Rejected")
        self.apply()
        self.assertEqual(self.student.instructor_applications.filter(status="pending").count(), 1)

    def test_approved_user_sees_approved_status(self):
        admin_user = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        InstructorApplication.objects.create(user=self.student, **APPLICATION_DATA).review(admin_user, approved=True)
        self.client.force_login(self.student)
        response = self.client.get(APPLICATION_URL)
        self.assertContains(response, "Approved")
        self.assertNotContains(response, "Submit application")


class ApplicationReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        cls.admin_user = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        cls.application = InstructorApplication.objects.create(user=cls.student, **APPLICATION_DATA)

    def run_action(self, user, action):
        self.client.force_login(user)
        data = {"action": action, "_selected_action": [self.application.pk]}
        response = self.client.post(ADMIN_APPLICATIONS_URL, data)
        self.application.refresh_from_db()
        self.student.refresh_from_db()
        return response

    def assert_still_pending(self):
        self.assertEqual(self.application.status, InstructorApplication.Status.PENDING)
        self.assertIsNone(self.application.reviewed_by)
        self.assertEqual(self.student.role, User.Role.STUDENT)

    def test_admin_can_approve_and_applicant_becomes_instructor(self):
        self.run_action(self.admin_user, "approve_applications")
        self.assertEqual(self.application.status, InstructorApplication.Status.APPROVED)
        self.assertEqual(self.student.role, User.Role.INSTRUCTOR)
        # Approval gives a role only, never admin access.
        self.assertFalse(self.student.is_staff or self.student.is_superuser)

    def test_admin_can_reject_and_applicant_stays_student(self):
        self.run_action(self.admin_user, "reject_applications")
        self.assertEqual(self.application.status, InstructorApplication.Status.REJECTED)
        self.assertEqual(self.student.role, User.Role.STUDENT)

    def test_review_information_is_saved(self):
        for action in ["approve_applications", "reject_applications"]:
            InstructorApplication.objects.filter(pk=self.application.pk).update(
                status="pending", reviewed_at=None, reviewed_by=None
            )
            self.run_action(self.admin_user, action)
            self.assertEqual(self.application.reviewed_by, self.admin_user)
            self.assertIsNotNone(self.application.reviewed_at)

    def test_reviewed_application_is_not_reviewed_again(self):
        self.run_action(self.admin_user, "reject_applications")
        first_review_time = self.application.reviewed_at
        self.run_action(self.admin_user, "approve_applications")
        self.assertEqual(self.application.status, InstructorApplication.Status.REJECTED)
        self.assertEqual(self.application.reviewed_at, first_review_time)
        self.assertEqual(self.student.role, User.Role.STUDENT)

    def test_student_cannot_approve_an_application(self):
        response = self.run_action(self.student, "approve_applications")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)
        self.assert_still_pending()

    def test_staff_without_permission_cannot_review(self):
        staff = User.objects.create_user(email="staff@example.com", password=PASSWORD, is_staff=True)
        response = self.run_action(staff, "approve_applications")
        self.assertEqual(response.status_code, 403)
        self.assert_still_pending()
        # View permission shows the list but does not offer the review actions.
        staff.user_permissions.add(Permission.objects.get(codename="view_instructorapplication"))
        self.run_action(staff, "approve_applications")
        self.assert_still_pending()

    def test_staff_with_change_permission_can_review(self):
        staff = User.objects.create_user(email="staff@example.com", password=PASSWORD, is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="change_instructorapplication"))
        self.run_action(staff, "approve_applications")
        self.assertEqual(self.application.status, InstructorApplication.Status.APPROVED)
        self.assertEqual(self.application.reviewed_by, staff)

    def test_nobody_can_review_their_own_application(self):
        # A student who applied and was later given admin access.
        User.objects.filter(pk=self.student.pk).update(is_staff=True, is_superuser=True)
        self.student.refresh_from_db()
        self.run_action(self.student, "approve_applications")
        self.assert_still_pending()

    def test_application_cannot_be_edited_or_added_in_admin(self):
        self.client.force_login(self.admin_user)
        change_url = reverse("admin:accounts_instructorapplication_change", args=[self.application.pk])
        self.assertEqual(self.client.get(change_url).status_code, 200)
        self.client.post(change_url, {"status": "approved", "full_name": "Changed"})
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, InstructorApplication.Status.PENDING)
        self.assertEqual(self.application.full_name, "Amina Ali")
        add_url = reverse("admin:accounts_instructorapplication_add")
        self.assertEqual(self.client.get(add_url).status_code, 403)

    def test_admin_search_by_name_email_and_phone(self):
        User.objects.filter(pk=self.student.pk).update(phone="+252615123456")
        self.client.force_login(self.admin_user)
        for query in ["Amina", "student@example.com", "+252615123456"]:
            response = self.client.get(ADMIN_APPLICATIONS_URL, {"q": query})
            self.assertContains(response, "Amina Ali")
        self.assertNotContains(self.client.get(ADMIN_APPLICATIONS_URL, {"q": "nobody"}), "Amina Ali")


class ModeratorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.moderator = User.objects.create_user(email="mod@example.com", password=PASSWORD, role="moderator")

    def test_moderator_role_gives_no_admin_privileges(self):
        self.assertFalse(self.moderator.is_staff or self.moderator.is_superuser)
        self.assertFalse(self.moderator.has_perm("accounts.change_user"))
        self.client.force_login(self.moderator)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_staff_moderator_cannot_use_superuser_only_pages(self):
        User.objects.filter(pk=self.moderator.pk).update(is_staff=True)
        self.client.force_login(self.moderator)
        self.assertEqual(self.client.get(reverse("admin:accounts_user_changelist")).status_code, 403)
        self.assertEqual(self.client.get(ADMIN_APPLICATIONS_URL).status_code, 403)

    def test_staff_moderator_cannot_make_anyone_a_superuser(self):
        # Even with permission to edit users, the admin flags stay locked.
        User.objects.filter(pk=self.moderator.pk).update(is_staff=True)
        self.moderator.user_permissions.add(Permission.objects.get(codename="change_user"))
        self.client.force_login(self.moderator)
        student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        response = self.client.post(
            reverse("admin:accounts_user_change", args=[student.pk]),
            {**USER_ADMIN_FORM, "email": "student@example.com", "first_name": "Saved", "is_staff": "on", "is_superuser": "on"},
        )
        self.assertEqual(response.status_code, 302)  # the form itself was saved
        student.refresh_from_db()
        self.assertEqual(student.first_name, "Saved")
        self.assertFalse(student.is_staff or student.is_superuser)


class StaffUserAdminLimitsTests(TestCase):
    """Staff who are not superusers, even with full user permissions."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        cls.staff = User.objects.create_user(email="staff@example.com", password=PASSWORD, is_staff=True)
        cls.staff.user_permissions.set(Permission.objects.filter(content_type__model="user"))

    def setUp(self):
        self.client.force_login(self.staff)

    def test_staff_cannot_change_a_superuser_password(self):
        url = reverse("admin:auth_user_password_change", args=[self.superuser.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        new_password = {"usable_password": "true", "password1": "Taken-Over-55!", "password2": "Taken-Over-55!"}
        self.assertEqual(self.client.post(url, new_password).status_code, 403)
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.check_password(PASSWORD))

    def test_staff_cannot_edit_a_superuser(self):
        url = reverse("admin:accounts_user_change", args=[self.superuser.pk])
        self.client.post(url, {**USER_ADMIN_FORM, "email": "taken-over@example.com"})
        self.superuser.refresh_from_db()
        self.assertEqual(self.superuser.email, "admin@example.com")
        self.assertTrue(self.superuser.is_superuser)

    def test_staff_cannot_delete_a_superuser(self):
        url = reverse("admin:accounts_user_delete", args=[self.superuser.pk])
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.superuser.pk).exists())

    def test_staff_cannot_edit_own_account_or_role(self):
        url = reverse("admin:accounts_user_change", args=[self.staff.pk])
        self.client.post(url, {**USER_ADMIN_FORM, "email": "staff@example.com", "role": "instructor"})
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, User.Role.STUDENT)

    def test_staff_can_still_manage_ordinary_users(self):
        student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        url = reverse("admin:accounts_user_change", args=[student.pk])
        response = self.client.post(url, {**USER_ADMIN_FORM, "email": "student@example.com", "first_name": "Saved"})
        self.assertEqual(response.status_code, 302)
        student.refresh_from_db()
        self.assertEqual(student.first_name, "Saved")

    def test_superuser_can_still_manage_superusers_and_self(self):
        self.client.force_login(self.superuser)
        url = reverse("admin:accounts_user_change", args=[self.superuser.pk])
        data = {**USER_ADMIN_FORM, "email": "admin@example.com", "first_name": "Saved", "is_staff": "on", "is_superuser": "on"}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.superuser.refresh_from_db()
        self.assertEqual(self.superuser.first_name, "Saved")
        password_url = reverse("admin:auth_user_password_change", args=[self.superuser.pk])
        self.assertEqual(self.client.get(password_url).status_code, 200)


class InstructorProfileTests(TestCase):
    PROFILE_URL = reverse("accounts:profile")

    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(email="teacher@example.com", password=PASSWORD, role="instructor")

    def test_instructor_can_view_and_update_profile(self):
        self.client.force_login(self.instructor)
        self.assertEqual(self.client.get(self.PROFILE_URL).status_code, 200)
        data = {"first_name": "Amina", "last_name": "Ali", "headline": "Maths teacher", "bio": "Ten years.", "website": ""}
        response = self.client.post(self.PROFILE_URL, data, follow=True)
        self.assertContains(response, "Your profile has been saved.")
        self.instructor.refresh_from_db()
        self.assertEqual(self.instructor.get_full_name(), "Amina Ali")
        self.assertEqual(self.instructor.headline, "Maths teacher")

    def test_profile_form_cannot_change_role_login_or_admin_flags(self):
        self.client.force_login(self.instructor)
        data = {"first_name": "Amina", "role": "moderator", "email": "changed@example.com", "is_staff": "on", "is_superuser": "on"}
        self.client.post(self.PROFILE_URL, data)
        self.instructor.refresh_from_db()
        self.assertEqual(self.instructor.role, User.Role.INSTRUCTOR)
        self.assertEqual(self.instructor.email, "teacher@example.com")
        self.assertFalse(self.instructor.is_staff or self.instructor.is_superuser)

    def test_profile_needs_login_and_students_do_not_get_teaching_fields(self):
        self.assertEqual(self.client.get(self.PROFILE_URL).status_code, 302)
        student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        self.client.force_login(student)
        response = self.client.get(self.PROFILE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("headline", response.context["form"].fields)
        self.client.force_login(self.instructor)
        self.assertIn("headline", self.client.get(self.PROFILE_URL).context["form"].fields)

    def test_approval_starts_the_profile_from_the_application(self):
        student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        admin_user = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        application = InstructorApplication.objects.create(user=student, **APPLICATION_DATA)
        application.review(admin_user, approved=True)
        student.refresh_from_db()
        self.assertEqual(student.headline, "Mathematics teacher")
        self.assertEqual(student.bio, "Ten years of teaching.")
