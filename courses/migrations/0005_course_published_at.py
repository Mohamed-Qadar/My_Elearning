from django.db import migrations, models


def fill_published_at(apps, schema_editor):
    """Courses that were already published get their last-changed time as a best estimate.

    The real publication moment was not recorded before this migration. Draft
    courses stay empty. No course is changed in any other way.
    """
    Course = apps.get_model("courses", "Course")
    for course in Course.objects.filter(status="published", published_at__isnull=True):
        Course.objects.filter(pk=course.pk).update(published_at=course.updated_at)


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0004_supported_material_formats"),
    ]

    operations = [
        migrations.AddField(
            model_name="course",
            name="published_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(fill_published_at, migrations.RunPython.noop),
    ]
