from django.db import migrations

# A starting list so instructors can create courses straight away.
# Administrators can add, rename or remove categories in the admin.
DEFAULT_CATEGORIES = [
    "Arts and Design",
    "Business",
    "Health",
    "Languages",
    "Mathematics and Science",
    "Personal Development",
    "Religious Studies",
    "Technology",
]


def add_default_categories(apps, schema_editor):
    Category = apps.get_model("courses", "Category")
    for name in DEFAULT_CATEGORIES:
        Category.objects.get_or_create(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0001_initial"),
    ]

    operations = [
        # Going backwards leaves the categories in place.
        migrations.RunPython(add_default_categories, migrations.RunPython.noop),
    ]
