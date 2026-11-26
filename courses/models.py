import os
import re
import zipfile

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import format_lazy
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from PIL import Image

THUMBNAIL_EXTENSIONS = ["jpg", "jpeg", "png", "webp"]
MAX_THUMBNAIL_MB = 2
THUMBNAIL_FORMATS = ["JPEG", "PNG", "WEBP"]
# The old Office formats (.doc, .ppt, .xls) are not accepted: their content cannot
# be checked reliably. Files uploaded before this rule stay downloadable.
MATERIAL_EXTENSIONS = ["pdf", "docx", "pptx", "xlsx", "txt"]
MAX_MATERIAL_MB = 20
# Office files are zip archives that must contain this part.
OFFICE_MAIN_PART = {"docx": "word/document.xml", "pptx": "ppt/presentation.xml", "xlsx": "xl/workbook.xml"}

YOUTUBE_URL = re.compile(
    r"^https?://(?:www\.|m\.)?"
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/)|youtu\.be/)"
    r"([\w-]{11})(?:[?&#/].*)?$"
)


def youtube_video_id(url):
    """Return the 11-character video id of a YouTube link, or None."""
    match = YOUTUBE_URL.match(url or "")
    return match.group(1) if match else None


def validate_youtube_url(url):
    if not youtube_video_id(url):
        raise ValidationError(_("Enter a valid YouTube video link, for example https://www.youtube.com/watch?v=..."))


def validate_thumbnail_size(image):
    if image.size > MAX_THUMBNAIL_MB * 1024 * 1024:
        raise ValidationError(_("The image is too large. The maximum size is %(size)s MB.") % {"size": MAX_THUMBNAIL_MB})


def validate_thumbnail_content(image):
    """The image data itself must be JPG, PNG or WebP, whatever the file is called."""
    try:
        image.seek(0)
        image_format = Image.open(image).format
    except Exception:
        image_format = None
    image.seek(0)
    if image_format not in THUMBNAIL_FORMATS:
        raise ValidationError(_("Upload a JPG, PNG or WebP image."))


def validate_material_size(file):
    if file.size > MAX_MATERIAL_MB * 1024 * 1024:
        raise ValidationError(_("The file is too large. The maximum size is %(size)s MB.") % {"size": MAX_MATERIAL_MB})


def is_office_file(file, main_part):
    """A real .docx, .pptx or .xlsx: a zip with the expected parts and no macros."""
    try:
        names = zipfile.ZipFile(file).namelist()
    except zipfile.BadZipFile:
        return False
    has_macros = any(name.endswith("vbaProject.bin") for name in names)
    return "[Content_Types].xml" in names and main_part in names and not has_macros


def validate_material_content(file):
    """Check the bytes of the file against its extension, not only its name."""
    extension = os.path.splitext(file.name)[1].lower().lstrip(".")
    file.seek(0)
    start = file.read(8)
    if extension == "pdf":
        valid = start.startswith(b"%PDF-")
    elif extension in OFFICE_MAIN_PART:
        valid = is_office_file(file, OFFICE_MAIN_PART[extension])
    elif extension == "txt":
        file.seek(0)
        valid = b"\x00" not in file.read()  # real text has no zero bytes
    else:
        valid = True  # any other extension is refused by the extension validator
    file.seek(0)
    if not valid:
        raise ValidationError(_("The content of this file does not match its type, so it was not accepted."))


class PrivateStorage(FileSystemStorage):
    """Keeps files outside the public media folder. They are only sent by a view."""

    @property
    def location(self):
        return str(settings.PRIVATE_MEDIA_ROOT)


def private_storage():
    return PrivateStorage()


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Course(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")

    class Language(models.TextChoices):
        ENGLISH = "en", _("English")
        SOMALI = "so", _("Somali")
        ARABIC = "ar", _("Arabic")

    class Level(models.TextChoices):
        BEGINNER = "beginner", _("Beginner")
        INTERMEDIATE = "intermediate", _("Intermediate")
        ADVANCED = "advanced", _("Advanced")
        ALL = "all", _("All levels")

    instructor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="courses")
    title = models.CharField(max_length=200)
    description = models.TextField(help_text=_("What is this course about, and who is it for?"))
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="courses")
    language = models.CharField(_("course language"), max_length=5, choices=Language.choices, default=Language.SOMALI)
    level = models.CharField(max_length=20, choices=Level.choices, default=Level.BEGINNER)
    # One currency for the whole platform, set by CURRENCY_CODE in the settings.
    price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text=_("Enter 0 for a free course."),
    )
    thumbnail = models.ImageField(
        _("course thumbnail"),
        upload_to="course_thumbnails/",
        blank=True,
        validators=[FileExtensionValidator(THUMBNAIL_EXTENSIONS), validate_thumbnail_size, validate_thumbnail_content],
        help_text=format_lazy(_("JPG, PNG or WebP, up to {size} MB."), size=MAX_THUMBNAIL_MB),
    )
    learning_objectives = models.TextField(help_text=_("What will students learn? Write one objective per line."))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    # Set when the course is published and cleared when it goes back to draft.
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        """Keep published_at in step with the status, wherever the status is changed."""
        if self.status != self.Status.PUBLISHED:
            self.published_at = None
        elif self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    @classmethod
    def published(cls):
        """The only courses visitors and students may see, most recently published first."""
        courses = cls.objects.filter(status=cls.Status.PUBLISHED).select_related("category", "instructor")
        return courses.order_by("-published_at", "-id")

    @property
    def is_free(self):
        return not self.price

    @property
    def price_display(self):
        return gettext("Free") if self.is_free else f"{settings.CURRENCY_SYMBOL}{self.price}"

    @property
    def currency_code(self):
        """The platform currency. Courses do not have currencies of their own."""
        return settings.CURRENCY_CODE


class Section(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class Lesson(models.Model):
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    youtube_url = models.URLField(_("YouTube video link"), blank=True, validators=[validate_youtube_url])
    notes = models.TextField(_("lesson notes"), blank=True, help_text=_("Written notes students can read with this lesson."))
    is_free_preview = models.BooleanField(
        _("free preview"), default=False, help_text=_("Anyone can watch a free preview lesson before buying the course.")
    )
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class Material(models.Model):
    """A private file for a course.

    It belongs to one section or one lesson, or to the whole course when both are empty.
    """

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="materials")
    section = models.ForeignKey(Section, on_delete=models.CASCADE, null=True, blank=True, related_name="materials")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, null=True, blank=True, related_name="materials")
    title = models.CharField(max_length=200)
    file = models.FileField(
        upload_to="materials/",
        storage=private_storage,
        validators=[FileExtensionValidator(MATERIAL_EXTENSIONS), validate_material_size, validate_material_content],
        help_text=format_lazy(
            _("PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx) or text (.txt), up to {size} MB."), size=MAX_MATERIAL_MB
        ),
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(section__isnull=True) | models.Q(lesson__isnull=True),
                name="material_not_in_both_section_and_lesson",
            ),
        ]

    def __str__(self):
        return self.title

    @property
    def filename(self):
        return os.path.basename(self.file.name)

    @property
    def extension(self):
        return os.path.splitext(self.file.name)[1].lower().lstrip(".")

    @property
    def can_be_viewed(self):
        """PDF and text files can be opened in the browser; the rest are downloaded."""
        return self.extension in ("pdf", "txt")


@receiver(post_delete, sender=Material)
def delete_material_file(sender, instance, **kwargs):
    """Remove the file from disk, also when a lesson or section delete cascades."""
    instance.file.delete(save=False)
