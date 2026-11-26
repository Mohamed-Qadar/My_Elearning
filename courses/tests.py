import io
import shutil
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import User
from learning.models import Enrollment

from .models import (
    MAX_MATERIAL_MB,
    OFFICE_MAIN_PART,
    Category,
    Course,
    Lesson,
    Material,
    Section,
    youtube_video_id,
)

PASSWORD = "Str0ng-Passw0rd!"
YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Uploaded test files go to a temporary folder, never to the real media folder.
TEMP_MEDIA = Path(tempfile.mkdtemp())


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)


def pdf(name="notes.pdf", content=b"%PDF-1.4 test"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def png(name="thumb.png", image_format="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(buffer, format=image_format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def office_file(name, extra_parts=()):
    """A minimal .docx, .pptx or .xlsx: a zip archive with the parts Office expects."""
    main_part = OFFICE_MAIN_PART[name.rsplit(".", 1)[-1]]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for part in ["[Content_Types].xml", main_part, *extra_parts]:
            archive.writestr(part, "<xml/>")
    return SimpleUploadedFile(name, buffer.getvalue())


def real_file(name):
    """A file whose content really matches the extension in its name."""
    extension = name.rsplit(".", 1)[-1]
    if extension == "pdf":
        return pdf(name)
    if extension in OFFICE_MAIN_PART:
        return office_file(name)
    return SimpleUploadedFile(name, b"Plain text notes.")


@override_settings(MEDIA_ROOT=TEMP_MEDIA / "public", PRIVATE_MEDIA_ROOT=TEMP_MEDIA / "private")
class InstructorTestCase(TestCase):
    """Two instructors, a student, and one course with a section and a lesson."""

    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(email="teacher@example.com", password=PASSWORD, role="instructor")
        cls.other_instructor = User.objects.create_user(email="other@example.com", password=PASSWORD, role="instructor")
        cls.student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        cls.category = Category.objects.create(name="Test category")
        cls.course = Course.objects.create(
            instructor=cls.instructor,
            title="Algebra",
            description="An algebra course.",
            category=cls.category,
            learning_objectives="Solve equations",
        )
        cls.section = Section.objects.create(course=cls.course, title="Introduction", order=1)
        cls.lesson = Lesson.objects.create(section=cls.section, title="Welcome", order=1)
        cls.other_course = Course.objects.create(
            instructor=cls.other_instructor,
            title="Biology",
            description="A biology course.",
            category=cls.category,
            learning_objectives="Know cells",
        )
        cls.other_section = Section.objects.create(course=cls.other_course, title="Cells", order=1)
        cls.other_lesson = Lesson.objects.create(section=cls.other_section, title="The cell", order=1)

    def setUp(self):
        self.client.force_login(self.instructor)

    def course_data(self, **changes):
        data = {
            "title": "Physics",
            "description": "A physics course.",
            "category": self.category.pk,
            "language": "en",
            "level": "beginner",
            "price": "10.00",
            "learning_objectives": "Understand motion\nUnderstand energy",
        }
        data.update(changes)
        return data

    def upload(self, course=None, **data):
        course = course or self.course
        data.setdefault("title", "Lecture notes")
        data.setdefault("file", pdf())
        return self.client.post(reverse("courses:material_upload", args=[course.pk]), data, follow=True)


class DashboardAccessTests(InstructorTestCase):
    def test_instructor_sees_dashboard_with_own_numbers_only(self):
        Course.objects.create(
            instructor=self.instructor, title="Published one", description="x", category=self.category,
            learning_objectives="x", status="published",
        )
        Enrollment.objects.create(student=self.student, course=self.course)
        # Another instructor's courses and students must not be counted.
        Enrollment.objects.create(student=self.student, course=self.other_course)
        response = self.client.get(reverse("courses:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_courses"], 2)
        self.assertEqual(response.context["published_courses"], 1)
        self.assertEqual(response.context["draft_courses"], 1)
        self.assertEqual(response.context["total_students"], 1)
        self.assertNotContains(response, "Biology")

    def test_new_instructor_sees_zeros(self):
        new_instructor = User.objects.create_user(email="new@example.com", password=PASSWORD, role="instructor")
        self.client.force_login(new_instructor)
        response = self.client.get(reverse("courses:dashboard"))
        self.assertEqual(response.context["total_courses"], 0)
        self.assertEqual(response.context["total_students"], 0)

    def test_every_instructor_page_requires_login_and_instructor_role(self):
        pages = [
            reverse("courses:dashboard"),
            reverse("courses:course_list"),
            reverse("courses:course_create"),
            reverse("courses:course_detail", args=[self.course.pk]),
            reverse("courses:course_edit", args=[self.course.pk]),
            reverse("courses:course_content", args=[self.course.pk]),
            reverse("courses:lesson_create", args=[self.section.pk]),
            reverse("courses:lesson_edit", args=[self.lesson.pk]),
            reverse("courses:students"),
        ]
        moderator = User.objects.create_user(email="mod@example.com", password=PASSWORD, role="moderator")
        admin_user = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        for page in pages:
            self.client.logout()
            response = self.client.get(page)
            self.assertRedirects(response, f"{reverse('accounts:login')}?next={page}")
            for user in [self.student, moderator, admin_user]:
                self.client.force_login(user)
                self.assertEqual(self.client.get(page).status_code, 403, f"{user} opened {page}")
            self.client.force_login(self.instructor)
            self.assertEqual(self.client.get(page).status_code, 200, page)

    def test_student_cannot_post_to_instructor_actions(self):
        self.client.force_login(self.student)
        actions = [
            (reverse("courses:course_create"), self.course_data()),
            (reverse("courses:course_edit", args=[self.course.pk]), self.course_data()),
            (reverse("courses:course_publish", args=[self.course.pk]), {"publish": "yes"}),
            (reverse("courses:course_content", args=[self.course.pk]), {"title": "Hacked"}),
            (reverse("courses:section_edit", args=[self.section.pk]), {"title": "Hacked"}),
            (reverse("courses:section_delete", args=[self.section.pk]), {}),
            (reverse("courses:section_move", args=[self.section.pk]), {"direction": "down"}),
            (reverse("courses:lesson_create", args=[self.section.pk]), {"title": "Hacked"}),
            (reverse("courses:lesson_edit", args=[self.lesson.pk]), {"title": "Hacked"}),
            (reverse("courses:lesson_delete", args=[self.lesson.pk]), {}),
            (reverse("courses:material_upload", args=[self.course.pk]), {"title": "Hacked", "file": pdf()}),
        ]
        for url, data in actions:
            self.assertEqual(self.client.post(url, data).status_code, 403, url)
        self.assertEqual(Course.objects.count(), 2)
        self.assertEqual(Section.objects.get(pk=self.section.pk).title, "Introduction")
        self.assertEqual(Lesson.objects.get(pk=self.lesson.pk).title, "Welcome")
        self.assertEqual(Material.objects.count(), 0)

    def test_instructor_actions_are_csrf_protected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.instructor)
        self.assertEqual(client.post(reverse("courses:course_create"), self.course_data()).status_code, 403)
        self.assertEqual(client.post(reverse("courses:section_delete", args=[self.section.pk])).status_code, 403)
        self.assertTrue(Section.objects.filter(pk=self.section.pk).exists())

    def test_destructive_actions_refuse_get(self):
        for name, pk in [("section_delete", self.section.pk), ("lesson_delete", self.lesson.pk),
                         ("course_publish", self.course.pk), ("section_move", self.section.pk)]:
            self.assertEqual(self.client.get(reverse(f"courses:{name}", args=[pk])).status_code, 405)


class CourseTests(InstructorTestCase):
    def test_create_course_as_draft(self):
        response = self.client.post(reverse("courses:course_create"), self.course_data(thumbnail=png()))
        course = Course.objects.get(title="Physics")
        self.assertRedirects(response, reverse("courses:course_content", args=[course.pk]))
        self.assertEqual(course.instructor, self.instructor)
        self.assertEqual(course.status, Course.Status.DRAFT)
        self.assertEqual(str(course.price), "10.00")
        self.assertTrue(course.thumbnail.name.startswith("course_thumbnails/"))

    def test_instructor_and_status_cannot_be_posted(self):
        data = self.course_data(instructor=self.other_instructor.pk, status="published")
        self.client.post(reverse("courses:course_create"), data)
        course = Course.objects.get(title="Physics")
        self.assertEqual(course.instructor, self.instructor)
        self.assertEqual(course.status, Course.Status.DRAFT)

    def test_course_validation_messages(self):
        response = self.client.post(reverse("courses:course_create"), self.course_data(title="", price="-5"))
        self.assertContains(response, "This field is required.")
        self.assertContains(response, "Ensure this value is greater than or equal to 0.")
        self.assertFalse(Course.objects.filter(description="A physics course.").exists())

    def test_thumbnail_must_be_an_image(self):
        fake = SimpleUploadedFile("thumb.png", b"not an image", content_type="image/png")
        response = self.client.post(reverse("courses:course_create"), self.course_data(thumbnail=fake))
        self.assertContains(response, "Upload a valid image.")
        self.assertFalse(Course.objects.filter(title="Physics").exists())

    def test_edit_course_keeps_status(self):
        Course.objects.filter(pk=self.course.pk).update(status="published")
        url = reverse("courses:course_edit", args=[self.course.pk])
        response = self.client.post(url, self.course_data(title="Algebra 2"))
        self.assertRedirects(response, reverse("courses:course_detail", args=[self.course.pk]))
        self.course.refresh_from_db()
        self.assertEqual(self.course.title, "Algebra 2")
        self.assertEqual(self.course.status, Course.Status.PUBLISHED)

    def test_publish_and_unpublish(self):
        url = reverse("courses:course_publish", args=[self.course.pk])
        self.client.post(url, {"publish": "yes"})
        self.course.refresh_from_db()
        self.assertEqual(self.course.status, Course.Status.PUBLISHED)
        self.client.post(url)
        self.course.refresh_from_db()
        self.assertEqual(self.course.status, Course.Status.DRAFT)

    def test_course_without_lessons_cannot_be_published(self):
        self.lesson.delete()
        url = reverse("courses:course_publish", args=[self.course.pk])
        response = self.client.post(url, {"publish": "yes"}, follow=True)
        self.assertContains(response, "Add at least one lesson before publishing this course.")
        self.course.refresh_from_db()
        self.assertEqual(self.course.status, Course.Status.DRAFT)

    def test_course_list_shows_only_own_courses_with_status(self):
        response = self.client.get(reverse("courses:course_list"))
        self.assertContains(response, "Algebra")
        self.assertContains(response, "Draft")
        self.assertNotContains(response, "Biology")


class OwnershipTests(InstructorTestCase):
    """Everything that belongs to another instructor answers 404 and stays unchanged."""

    def test_cannot_view_another_instructors_pages(self):
        for name, pk in [
            ("course_detail", self.other_course.pk),
            ("course_edit", self.other_course.pk),
            ("course_content", self.other_course.pk),
            ("lesson_create", self.other_section.pk),
            ("lesson_edit", self.other_lesson.pk),
        ]:
            self.assertEqual(self.client.get(reverse(f"courses:{name}", args=[pk])).status_code, 404, name)

    def test_cannot_change_another_instructors_course(self):
        material = Material.objects.create(course=self.other_course, title="Theirs", file=pdf())
        actions = [
            ("course_edit", self.other_course.pk, self.course_data()),
            ("course_publish", self.other_course.pk, {"publish": "yes"}),
            ("course_content", self.other_course.pk, {"title": "Hacked"}),
            ("section_edit", self.other_section.pk, {"title": "Hacked"}),
            ("section_move", self.other_section.pk, {"direction": "down"}),
            ("section_delete", self.other_section.pk, {}),
            ("lesson_create", self.other_section.pk, {"title": "Hacked"}),
            ("lesson_edit", self.other_lesson.pk, {"title": "Hacked"}),
            ("lesson_move", self.other_lesson.pk, {"direction": "down"}),
            ("lesson_delete", self.other_lesson.pk, {}),
            ("material_upload", self.other_course.pk, {"title": "Hacked", "file": pdf()}),
            ("material_replace", material.pk, {"file": pdf("new.pdf")}),
            ("material_delete", material.pk, {}),
        ]
        for name, pk, data in actions:
            response = self.client.post(reverse(f"courses:{name}", args=[pk]), data)
            self.assertEqual(response.status_code, 404, name)
        self.other_course.refresh_from_db()
        self.assertEqual(self.other_course.title, "Biology")
        self.assertEqual(self.other_course.status, Course.Status.DRAFT)
        self.assertEqual(list(self.other_course.sections.values_list("title", flat=True)), ["Cells"])
        self.assertEqual(list(self.other_section.lessons.values_list("title", flat=True)), ["The cell"])
        self.assertEqual(list(self.other_course.materials.values_list("title", flat=True)), ["Theirs"])

    def test_material_cannot_be_attached_to_another_courses_section_or_lesson(self):
        for target in [f"lesson-{self.other_lesson.pk}", f"section-{self.other_section.pk}", "lesson-999999", "junk"]:
            response = self.upload(attach_to=target)
            self.assertContains(response, "Select a valid choice.", msg_prefix=target)
        self.assertEqual(Material.objects.count(), 0)


class SectionAndLessonTests(InstructorTestCase):
    def test_add_rename_and_delete_section(self):
        content = reverse("courses:course_content", args=[self.course.pk])
        self.client.post(content, {"title": "Equations"})
        section = Section.objects.get(title="Equations")
        self.assertEqual((section.course, section.order), (self.course, 2))

        self.client.post(reverse("courses:section_edit", args=[section.pk]), {"title": "Linear equations"})
        section.refresh_from_db()
        self.assertEqual(section.title, "Linear equations")

        self.client.post(reverse("courses:section_delete", args=[section.pk]))
        self.assertFalse(Section.objects.filter(pk=section.pk).exists())

    def test_section_title_is_required(self):
        content = reverse("courses:course_content", args=[self.course.pk])
        response = self.client.post(content, {"title": ""})
        self.assertContains(response, "This field is required.")
        self.assertEqual(self.course.sections.count(), 1)

    def test_add_edit_and_delete_lesson(self):
        create = reverse("courses:lesson_create", args=[self.section.pk])
        data = {"title": "Variables", "description": "About variables.", "youtube_url": YOUTUBE,
                "notes": "Remember: x is unknown.", "is_free_preview": "on"}
        self.client.post(create, data)
        lesson = Lesson.objects.get(title="Variables")
        self.assertEqual((lesson.section, lesson.order), (self.section, 2))
        self.assertEqual(lesson.youtube_url, YOUTUBE)
        self.assertEqual(lesson.notes, "Remember: x is unknown.")
        self.assertTrue(lesson.is_free_preview)

        edit = reverse("courses:lesson_edit", args=[lesson.pk])
        self.client.post(edit, {"title": "Variables and constants", "description": "", "youtube_url": "", "notes": ""})
        lesson.refresh_from_db()
        self.assertEqual(lesson.title, "Variables and constants")
        self.assertFalse(lesson.is_free_preview)

        self.client.post(reverse("courses:lesson_delete", args=[lesson.pk]))
        self.assertFalse(Lesson.objects.filter(pk=lesson.pk).exists())

    def test_only_youtube_links_are_accepted(self):
        create = reverse("courses:lesson_create", args=[self.section.pk])
        for link in ["https://vimeo.com/12345", "https://evil.example.com/watch?v=dQw4w9WgXcQ", "not a link"]:
            response = self.client.post(create, {"title": "Bad video", "youtube_url": link})
            self.assertEqual(response.status_code, 200, link)
            self.assertTrue(response.context["form"].errors["youtube_url"], link)
        self.assertFalse(Lesson.objects.filter(title="Bad video").exists())

    def test_youtube_link_formats(self):
        for link in [YOUTUBE, "https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/embed/dQw4w9WgXcQ",
                     "https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ"]:
            self.assertEqual(youtube_video_id(link), "dQw4w9WgXcQ", link)

    def test_change_lesson_order(self):
        second = Lesson.objects.create(section=self.section, title="Second", order=2)
        third = Lesson.objects.create(section=self.section, title="Third", order=3)
        self.client.post(reverse("courses:lesson_move", args=[third.pk]), {"direction": "up"})
        self.assertEqual(list(self.section.lessons.values_list("title", flat=True)), ["Welcome", "Third", "Second"])
        self.client.post(reverse("courses:lesson_move", args=[self.lesson.pk]), {"direction": "down"})
        self.assertEqual(list(self.section.lessons.values_list("title", flat=True)), ["Third", "Welcome", "Second"])
        # Moving the first item up, or the last item down, changes nothing.
        self.client.post(reverse("courses:lesson_move", args=[third.pk]), {"direction": "up"})
        self.client.post(reverse("courses:lesson_move", args=[second.pk]), {"direction": "down"})
        self.assertEqual(list(self.section.lessons.values_list("title", flat=True)), ["Third", "Welcome", "Second"])

    def test_change_section_order(self):
        second = Section.objects.create(course=self.course, title="Second", order=2)
        self.client.post(reverse("courses:section_move", args=[second.pk]), {"direction": "up"})
        self.assertEqual(list(self.course.sections.values_list("title", flat=True)), ["Second", "Introduction"])


class MaterialTests(InstructorTestCase):
    def test_upload_material_for_course_and_for_lesson(self):
        response = self.upload(title="Syllabus")
        self.assertContains(response, "Material uploaded.")
        self.upload(title="Lesson slides", file=real_file("slides.pptx"), attach_to=f"lesson-{self.lesson.pk}")
        syllabus = Material.objects.get(title="Syllabus")
        slides = Material.objects.get(title="Lesson slides")
        self.assertEqual((syllabus.course, syllabus.lesson), (self.course, None))
        self.assertEqual((slides.course, slides.lesson), (self.course, self.lesson))
        # Stored in the private folder, not in the public media folder.
        self.assertTrue(Path(syllabus.file.path).is_relative_to(TEMP_MEDIA / "private"))
        self.assertTrue(Path(syllabus.file.path).exists())

    def test_allowed_file_types(self):
        for name in ["a.pdf", "a.docx", "a.pptx", "a.xlsx", "a.txt"]:
            self.upload(title=name, file=real_file(name))
            self.assertTrue(Material.objects.filter(title=name).exists(), name)

    def test_disallowed_file_types_are_rejected(self):
        for name in ["virus.exe", "page.html", "script.js", "image.svg", "archive.zip", "noextension"]:
            response = self.upload(title=name, file=pdf(name))
            self.assertContains(response, "is not allowed", msg_prefix=name)
        self.assertEqual(Material.objects.count(), 0)

    def test_too_large_file_is_rejected(self):
        big = pdf(content=b"x" * (MAX_MATERIAL_MB * 1024 * 1024 + 1))
        response = self.upload(file=big)
        self.assertContains(response, "The file is too large.")
        self.assertEqual(Material.objects.count(), 0)

    def test_replace_material_file(self):
        self.upload()
        material = Material.objects.get()
        old_path = Path(material.file.path)
        url = reverse("courses:material_replace", args=[material.pk])
        new_file = real_file("version2.docx")
        new_content = new_file.read()
        new_file.seek(0)
        response = self.client.post(url, {"file": new_file}, follow=True)
        self.assertContains(response, "File replaced.")
        material.refresh_from_db()
        self.assertEqual(material.title, "Lecture notes")
        self.assertTrue(material.filename.endswith(".docx"))
        self.assertEqual(Path(material.file.path).read_bytes(), new_content)
        self.assertFalse(old_path.exists())

    def test_replace_with_bad_file_keeps_the_old_one(self):
        self.upload()
        material = Material.objects.get()
        url = reverse("courses:material_replace", args=[material.pk])
        self.client.post(url, {"file": pdf("virus.exe")})
        response = self.client.post(url, {"file": pdf("fake.docx")}, follow=True)
        self.assertContains(response, "does not match its type")
        self.client.post(url, {})
        material.refresh_from_db()
        self.assertTrue(material.filename.endswith(".pdf"))
        self.assertTrue(Path(material.file.path).exists())

    def test_delete_material_removes_the_file(self):
        self.upload()
        material = Material.objects.get()
        path = Path(material.file.path)
        self.client.post(reverse("courses:material_delete", args=[material.pk]))
        self.assertEqual(Material.objects.count(), 0)
        self.assertFalse(path.exists())

    def test_deleting_a_lesson_removes_its_material_files(self):
        self.upload(attach_to=f"lesson-{self.lesson.pk}")
        path = Path(Material.objects.get().file.path)
        self.client.post(reverse("courses:lesson_delete", args=[self.lesson.pk]))
        self.assertEqual(Material.objects.count(), 0)
        self.assertFalse(path.exists())


class LegacyOfficeFormatTests(InstructorTestCase):
    """.doc, .ppt and .xls are no longer accepted, but old records keep working."""

    # A real old Office file starts with these bytes.
    OLD_OFFICE_FILE = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 64

    def test_legacy_formats_are_rejected_on_upload(self):
        for name in ["old.doc", "old.ppt", "old.xls", "OLD.DOC"]:
            response = self.upload(title=name, file=SimpleUploadedFile(name, self.OLD_OFFICE_FILE))
            self.assertContains(response, "is not allowed", msg_prefix=name)
        self.assertEqual(Material.objects.count(), 0)

    def test_legacy_formats_are_rejected_on_replace(self):
        self.upload()
        material = Material.objects.get()
        url = reverse("courses:material_replace", args=[material.pk])
        response = self.client.post(url, {"file": SimpleUploadedFile("old.doc", self.OLD_OFFICE_FILE)}, follow=True)
        self.assertContains(response, "is not allowed")
        material.refresh_from_db()
        self.assertTrue(material.filename.endswith(".pdf"))

    def test_existing_legacy_material_is_kept_and_still_downloads(self):
        # A record from before the rule, saved without going through the upload form.
        old = Material.objects.create(
            course=self.course, title="Old handout", file=SimpleUploadedFile("old.doc", self.OLD_OFFICE_FILE)
        )
        response = self.client.get(reverse("courses:course_content", args=[self.course.pk]))
        self.assertContains(response, "Old handout")
        download = self.client.get(reverse("courses:material_download", args=[old.pk]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), self.OLD_OFFICE_FILE)
        # It can be replaced with a supported file, and deleted, like any other.
        self.client.post(reverse("courses:material_replace", args=[old.pk]), {"file": real_file("new.docx")})
        old.refresh_from_db()
        self.assertTrue(old.filename.endswith(".docx"))

    def test_upload_form_lists_only_supported_types(self):
        response = self.client.get(reverse("courses:course_content", args=[self.course.pk]))
        self.assertContains(response, 'accept=".pdf,.docx,.pptx,.xlsx,.txt"')
        self.assertContains(response, "Word (.docx), PowerPoint (.pptx), Excel (.xlsx)")


class MaterialViewTests(InstructorTestCase):
    def test_pdf_and_text_can_be_opened_in_the_browser(self):
        for name in ["notes.pdf", "notes.txt"]:
            self.upload(title=name, file=real_file(name))
            url = reverse("courses:material_download", args=[Material.objects.get(title=name).pk])
            self.assertIn("inline", self.client.get(url + "?view=1")["Content-Disposition"])
            self.assertIn("attachment", self.client.get(url)["Content-Disposition"])

    def test_office_files_are_always_downloaded(self):
        self.upload(title="slides", file=real_file("slides.pptx"))
        url = reverse("courses:material_download", args=[Material.objects.get().pk])
        self.assertIn("attachment", self.client.get(url + "?view=1")["Content-Disposition"])

    def test_viewing_follows_the_same_access_rules(self):
        self.upload()
        url = reverse("courses:material_download", args=[Material.objects.get().pk]) + "?view=1"
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.other_instructor)
        self.assertEqual(self.client.get(url).status_code, 404)


class SectionMaterialTests(InstructorTestCase):
    def upload_to_section(self):
        self.upload(title="Section handout", attach_to=f"section-{self.section.pk}")
        return Material.objects.get(title="Section handout")

    def test_upload_and_view_section_material(self):
        material = self.upload_to_section()
        self.assertEqual((material.course, material.section, material.lesson), (self.course, self.section, None))
        self.assertTrue(Path(material.file.path).is_relative_to(TEMP_MEDIA / "private"))
        response = self.client.get(reverse("courses:course_content", args=[self.course.pk]))
        self.assertContains(response, "Section handout")
        self.assertContains(response, "Section: Introduction")

    def test_replace_and_delete_section_material(self):
        material = self.upload_to_section()
        old_path = Path(material.file.path)
        self.client.post(reverse("courses:material_replace", args=[material.pk]), {"file": real_file("new.pptx")})
        material.refresh_from_db()
        # Replacing the file keeps the material attached to its section.
        self.assertEqual((material.section, material.lesson), (self.section, None))
        self.assertTrue(material.filename.endswith(".pptx"))
        self.assertFalse(old_path.exists())
        new_path = Path(material.file.path)
        self.client.post(reverse("courses:material_delete", args=[material.pk]))
        self.assertEqual(Material.objects.count(), 0)
        self.assertFalse(new_path.exists())

    def test_deleting_the_section_removes_its_material_files(self):
        path = Path(self.upload_to_section().file.path)
        self.client.post(reverse("courses:section_delete", args=[self.section.pk]))
        self.assertEqual(Material.objects.count(), 0)
        self.assertFalse(path.exists())

    def test_section_material_download_follows_the_same_access_rules(self):
        url = reverse("courses:material_download", args=[self.upload_to_section().pk])
        self.assertEqual(self.client.get(url).status_code, 200)  # the owner
        self.client.force_login(self.other_instructor)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(url).status_code, 404)
        Enrollment.objects.create(student=self.student, course=self.course)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_other_instructor_cannot_replace_or_delete_section_material(self):
        material = self.upload_to_section()
        self.client.force_login(self.other_instructor)
        replace = reverse("courses:material_replace", args=[material.pk])
        self.assertEqual(self.client.post(replace, {"file": real_file("new.pdf")}).status_code, 404)
        self.assertEqual(self.client.post(reverse("courses:material_delete", args=[material.pk])).status_code, 404)
        material.refresh_from_db()
        self.assertTrue(material.filename.endswith(".pdf"))

    def test_material_cannot_belong_to_both_a_section_and_a_lesson(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Material.objects.create(
                course=self.course, section=self.section, lesson=self.lesson, title="Both", file=pdf()
            )


class FileContentValidationTests(InstructorTestCase):
    """The bytes of an upload must match its extension, whatever the browser says."""

    REJECTED = "does not match its type"

    def assert_rejected(self, file):
        response = self.upload(title=file.name, file=file)
        self.assertContains(response, self.REJECTED, msg_prefix=file.name)
        self.assertFalse(Material.objects.filter(title=file.name).exists(), file.name)

    def test_renamed_files_are_rejected(self):
        program = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64
        page = b"<html><script>alert(1)</script></html>"
        for name in ["a.pdf", "a.docx", "a.pptx", "a.xlsx"]:
            self.assert_rejected(SimpleUploadedFile(name, program))
            self.assert_rejected(SimpleUploadedFile("page-" + name, page))
        self.assert_rejected(SimpleUploadedFile("program.txt", program))

    def test_browser_supplied_type_is_not_trusted(self):
        fake = SimpleUploadedFile("fake.pdf", b"MZ not a pdf", content_type="application/pdf")
        self.assert_rejected(fake)

    def test_office_files_must_match_their_own_type(self):
        self.assert_rejected(pdf("really-a-pdf.docx"))
        # A Word file renamed to PowerPoint, and a plain zip renamed to Word.
        word_as_slides = SimpleUploadedFile("slides.pptx", office_file("x.docx").read())
        self.assert_rejected(word_as_slides)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("anything.txt", "hello")
        self.assert_rejected(SimpleUploadedFile("archive.docx", buffer.getvalue()))

    def test_office_files_with_macros_are_rejected(self):
        self.assert_rejected(office_file("macro.docx", extra_parts=["word/vbaProject.bin"]))
        self.assert_rejected(office_file("macro.xlsx", extra_parts=["xl/vbaProject.bin"]))

    def test_size_limit_still_applies_to_real_files(self):
        big = pdf("big.pdf", b"%PDF-1.4 " + b"x" * (MAX_MATERIAL_MB * 1024 * 1024))
        response = self.upload(title="big", file=big)
        self.assertContains(response, "The file is too large.")
        self.assertNotContains(response, self.REJECTED)
        self.assertEqual(Material.objects.count(), 0)

    def test_thumbnail_content_must_be_jpg_png_or_webp(self):
        create = reverse("courses:course_create")
        # A GIF image saved under a .png name.
        response = self.client.post(create, self.course_data(thumbnail=png("thumb.png", "GIF")))
        self.assertContains(response, "Upload a JPG, PNG or WebP image.")
        self.assertFalse(Course.objects.filter(title="Physics").exists())
        for image_format, name in [("JPEG", "a.jpg"), ("PNG", "a.png"), ("WEBP", "a.webp")]:
            self.client.post(create, self.course_data(title=name, thumbnail=png(name, image_format)))
            self.assertTrue(Course.objects.filter(title=name).exists(), name)


class CurrencyTests(InstructorTestCase):
    def test_default_currency(self):
        Course.objects.filter(pk=self.course.pk).update(price="12.50")
        self.assertContains(self.client.get(reverse("courses:course_list")), "$12.50")
        self.assertContains(self.client.get(reverse("courses:course_create")), "Price (USD)")

    @override_settings(CURRENCY_CODE="SOS", CURRENCY_SYMBOL="Sh ")
    def test_currency_comes_from_settings(self):
        Course.objects.filter(pk=self.course.pk).update(price="12.50")
        for page in [reverse("courses:course_list"), reverse("courses:course_detail", args=[self.course.pk])]:
            response = self.client.get(page)
            self.assertContains(response, "Sh 12.50")
            self.assertNotContains(response, "$")
        self.assertContains(self.client.get(reverse("courses:course_create")), "Price (SOS)")

    def test_free_course(self):
        self.assertContains(self.client.get(reverse("courses:course_list")), "Free")


class PrivateMaterialAccessTests(InstructorTestCase):
    def setUp(self):
        super().setUp()
        self.upload()
        self.material = Material.objects.get()
        self.url = reverse("courses:material_download", args=[self.material.pk])

    def test_owner_can_download(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 test")

    def test_anonymous_user_is_sent_to_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('accounts:login')}?next={self.url}")

    def test_student_who_is_not_enrolled_cannot_download(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        # Being enrolled in a different course does not help.
        Enrollment.objects.create(student=self.student, course=self.other_course)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_enrolled_student_can_download(self):
        Enrollment.objects.create(student=self.student, course=self.course)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_another_instructor_cannot_download(self):
        self.client.force_login(self.other_instructor)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_file_is_not_reachable_through_the_public_media_url(self):
        response = self.client.get("/media/" + self.material.file.name)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get("/media/private/" + self.material.file.name).status_code, 404)


class StudentOverviewTests(InstructorTestCase):
    def test_shows_only_students_of_own_courses_without_contact_details(self):
        named = User.objects.create_user(
            email="amina@example.com", phone="0615123456", password=PASSWORD, first_name="Amina", last_name="Ali"
        )
        elsewhere = User.objects.create_user(email="elsewhere@example.com", password=PASSWORD, first_name="Other")
        Enrollment.objects.create(student=named, course=self.course)
        Enrollment.objects.create(student=self.student, course=self.course)
        Enrollment.objects.create(student=elsewhere, course=self.other_course)
        response = self.client.get(reverse("courses:students"))
        self.assertContains(response, "Amina Ali")
        self.assertContains(response, f"#{self.student.pk}</span>")
        self.assertNotContains(response, "Other")
        self.assertNotContains(response, "amina@example.com")
        self.assertNotContains(response, "student@example.com")
        self.assertNotContains(response, "+252615123456")


@override_settings(MEDIA_ROOT=TEMP_MEDIA / "public", PRIVATE_MEDIA_ROOT=TEMP_MEDIA / "private")
class PublicCatalogTests(TestCase):
    """What visitors can see: published courses only, and nothing private."""

    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            email="teacher@example.com", phone="0615123456", password=PASSWORD, role="instructor",
            first_name="Tina", last_name="Teacher", headline="Maths teacher",
        )
        cls.maths = Category.objects.create(name="Maths test")
        cls.science = Category.objects.create(name="Science test")

        def course(title, **fields):
            fields.setdefault("status", Course.Status.PUBLISHED)
            fields.setdefault("category", cls.maths)
            return Course.objects.create(
                instructor=cls.instructor, title=title, description="A description.",
                learning_objectives="Solve equations", **fields,
            )

        cls.algebra = course("Algebra basics", language="en", level="beginner", price="20.00")
        cls.geometry = course("Geometry", language="so", level="advanced")
        cls.physics = course("Physics", category=cls.science, language="en", level="beginner")
        cls.draft = course("Secret draft", status=Course.Status.DRAFT)
        section = Section.objects.create(course=cls.algebra, title="Numbers", order=1)
        Lesson.objects.create(section=section, title="Counting", order=1, is_free_preview=True)
        Lesson.objects.create(
            section=section, title="Fractions", order=2,
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk", notes="Hidden lesson notes.",
        )
        Material.objects.create(
            course=cls.algebra, title="Hidden handout", file=SimpleUploadedFile("hidden-handout.pdf", b"%PDF-1.4 x")
        )

    def titles(self, **params):
        response = self.client.get(reverse("courses:catalog"), params)
        return sorted(course.title for course in response.context["page"])

    def test_catalog_lists_published_courses_only(self):
        self.assertEqual(self.titles(), ["Algebra basics", "Geometry", "Physics"])
        response = self.client.get(reverse("courses:catalog"))
        self.assertNotContains(response, "Secret draft")
        self.assertContains(response, "Tina Teacher")
        self.assertContains(response, "$20.00")
        self.assertContains(response, "Free")

    def test_instructor_contact_details_are_never_shown(self):
        for url in [reverse("core:home"), reverse("courses:catalog"), reverse("courses:detail", args=[self.algebra.pk])]:
            response = self.client.get(url)
            self.assertNotContains(response, "teacher@example.com")
            self.assertNotContains(response, "+252615123456")

    def test_search_by_title(self):
        self.assertEqual(self.titles(q="geo"), ["Geometry"])
        self.assertEqual(self.titles(q="ALGEBRA"), ["Algebra basics"])
        self.assertEqual(self.titles(q="secret"), [])
        self.assertContains(self.client.get(reverse("courses:catalog"), {"q": "zzz"}), "No courses match your search")

    def test_filters(self):
        self.assertEqual(self.titles(category=self.science.pk), ["Physics"])
        self.assertEqual(self.titles(language="so"), ["Geometry"])
        self.assertEqual(self.titles(level="beginner"), ["Algebra basics", "Physics"])
        self.assertEqual(self.titles(level="beginner", category=self.maths.pk, language="en"), ["Algebra basics"])
        self.assertEqual(self.titles(q="phys", level="advanced"), [])

    def test_unknown_filter_values_are_ignored(self):
        everything = ["Algebra basics", "Geometry", "Physics"]
        self.assertEqual(self.titles(category="abc", language="xx", level="expert"), everything)
        self.assertEqual(self.titles(page="999"), everything)

    def test_pagination_keeps_the_filters(self):
        for number in range(10):
            Course.objects.create(
                instructor=self.instructor, title=f"Extra {number}", description="x", learning_objectives="x",
                category=self.science, status=Course.Status.PUBLISHED, language="en",
            )
        first = self.client.get(reverse("courses:catalog"), {"language": "en"})
        self.assertEqual(len(first.context["page"]), 9)
        self.assertEqual(first.context["page"].paginator.count, 12)
        self.assertContains(first, "?language=en&amp;page=2")
        second = self.client.get(reverse("courses:catalog"), {"language": "en", "page": 2})
        self.assertEqual(len(second.context["page"]), 3)

    def test_detail_page_shows_the_course(self):
        response = self.client.get(reverse("courses:detail", args=[self.algebra.pk]))
        for text in ["Algebra basics", "A description.", "Tina Teacher", "Maths teacher", "Maths test", "English",
                     "Beginner", "$20.00", "Solve equations", "Numbers", "Counting", "Fractions", "Free preview"]:
            self.assertContains(response, text)

    def test_detail_page_exposes_nothing_private(self):
        response = self.client.get(reverse("courses:detail", args=[self.algebra.pk]))
        for secret in ["abcdefghijk", "youtube", "Hidden lesson notes", "Hidden handout", "hidden-handout", "/download/"]:
            self.assertNotContains(response, secret)
        # Only the free preview lesson is a link.
        lessons = {lesson.title: lesson for lesson in Lesson.objects.filter(section__course=self.algebra)}
        self.assertContains(response, reverse("learning:lesson", args=[lessons["Counting"].pk]))
        self.assertNotContains(response, reverse("learning:lesson", args=[lessons["Fractions"].pk]))

    def test_draft_course_page_is_not_found_for_everyone(self):
        url = reverse("courses:detail", args=[self.draft.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        for user in [student, self.instructor]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_paid_course_offers_no_enrollment(self):
        student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        self.client.force_login(student)
        response = self.client.get(reverse("courses:detail", args=[self.algebra.pk]))
        self.assertContains(response, "Online payment is not available yet")
        self.assertNotContains(response, reverse("learning:enroll", args=[self.algebra.pk]))

    def test_free_course_offers_enrollment_or_login(self):
        url = reverse("courses:detail", args=[self.geometry.pk])
        self.assertContains(self.client.get(url), "Log in to enroll for free")
        student = User.objects.create_user(email="student@example.com", password=PASSWORD)
        self.client.force_login(student)
        self.assertContains(self.client.get(url), reverse("learning:enroll", args=[self.geometry.pk]))
        Enrollment.objects.create(student=student, course=self.geometry)
        self.assertContains(self.client.get(url), "Continue learning")


class PublicationDateTests(InstructorTestCase):
    """published_at records when a course was published; it is not the creation date."""

    def publish(self, course, publish=True):
        url = reverse("courses:course_publish", args=[course.pk])
        self.client.post(url, {"publish": "yes"} if publish else {})
        course.refresh_from_db()

    def test_new_draft_has_no_publication_date(self):
        self.assertIsNone(self.course.published_at)

    def test_publishing_sets_the_date_and_unpublishing_clears_it(self):
        self.publish(self.course)
        self.assertEqual(self.course.status, Course.Status.PUBLISHED)
        self.assertIsNotNone(self.course.published_at)
        self.assertGreater(self.course.published_at, self.course.created_at)
        first_time = self.course.published_at

        # Editing a published course keeps its publication date.
        self.client.post(reverse("courses:course_edit", args=[self.course.pk]), self.course_data(title="Algebra 2"))
        self.course.refresh_from_db()
        self.assertEqual(self.course.published_at, first_time)

        self.publish(self.course, publish=False)
        self.assertIsNone(self.course.published_at)
        self.publish(self.course)
        self.assertGreater(self.course.published_at, first_time)

    def test_status_changed_elsewhere_also_sets_the_date(self):
        # For example an administrator saving the course in the Django admin.
        self.course.status = Course.Status.PUBLISHED
        self.course.save()
        self.assertIsNotNone(self.course.published_at)

    def test_recently_published_follows_publication_not_creation(self):
        self.client.logout()
        older = self.course  # created first
        newer = Course.objects.create(
            instructor=self.instructor, title="Created later", description="x", category=self.category,
            learning_objectives="x",
        )
        Lesson.objects.create(section=Section.objects.create(course=newer, title="S", order=1), title="L", order=1)
        self.client.force_login(self.instructor)
        self.publish(newer)
        # Two publications can land on the same clock tick, so make the gap explicit.
        Course.objects.filter(pk=newer.pk).update(published_at=newer.published_at - timedelta(minutes=1))
        self.publish(older)  # the older course is published last
        self.client.logout()
        home = self.client.get(reverse("core:home"))
        self.assertEqual([course.title for course in home.context["recent_courses"]], ["Algebra", "Created later"])
        catalog = self.client.get(reverse("courses:catalog"))
        self.assertEqual([course.title for course in catalog.context["page"]], ["Algebra", "Created later"])

    def test_course_page_shows_the_publication_date(self):
        self.publish(self.course)
        response = self.client.get(reverse("courses:detail", args=[self.course.pk]))
        self.assertContains(response, self.course.published_at.strftime("%Y"))
        self.assertContains(response, "Published")
