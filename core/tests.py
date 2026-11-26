from django.test import TestCase

from accounts.models import User
from courses.models import Category, Course
from learning.models import Enrollment


class FaviconTests(TestCase):
    def test_favicon_ico_redirects_to_the_site_icon(self):
        response = self.client.get("/favicon.ico")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("images/favicon.svg"))


class HomePageTests(TestCase):
    def test_empty_site_has_no_placeholder_text(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "The project foundation is ready")
        self.assertContains(response, "Courses are coming soon")
        for text in ["Browse courses", "Log in", "Register", "Become an instructor"]:
            self.assertContains(response, text)

    def test_home_shows_published_courses_only(self):
        teacher = User.objects.create_user(email="teacher@example.com", password="Str0ng-Passw0rd!", role="instructor")
        used, unused = Category.objects.create(name="Used test"), Category.objects.create(name="Unused test")

        def course(title, status, category=used):
            return Course.objects.create(
                instructor=teacher, title=title, description="x", learning_objectives="x", category=category, status=status
            )

        popular, quiet = course("Popular course", "published"), course("Quiet course", "published")
        course("Hidden draft", "draft", unused)
        student = User.objects.create_user(email="student@example.com", password="Str0ng-Passw0rd!")
        Enrollment.objects.create(student=student, course=popular)

        response = self.client.get("/")
        self.assertContains(response, "Popular course")
        self.assertContains(response, "Quiet course")
        self.assertNotContains(response, "Hidden draft")
        self.assertEqual(response.context["featured_courses"][0], popular)  # most students first
        self.assertEqual([category.name for category in response.context["categories"]], ["Used test"])
        self.assertEqual((response.context["course_count"], response.context["instructor_count"]), (2, 1))
