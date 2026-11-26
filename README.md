# E-Learning Platform

A simple, traditional Django application: Django Templates, Bootstrap 5, Vanilla JavaScript and SQLite.
PostgreSQL will be introduced later for production deployment.

Development rules are in [CLAUDE.md](CLAUDE.md).

## Apps

- `accounts` – users
- `courses` – courses and lessons
- `learning` – student learning records
- `payments` – payments
- `core` – home page and shared views

## Setup

```
pip install -r requirements.txt
copy .env.example .env
```

Set `SECRET_KEY` in `.env`, then:

```
python manage.py migrate
python manage.py check
python manage.py runserver
```

## Course materials

Instructors can upload PDF, Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx`) and text (`.txt`)
files of up to 20 MB. The old Office formats (`.doc`, `.ppt`, `.xls`) are not accepted.
Materials are stored in `media/private/` and are only sent to the course's instructor
and to enrolled students.

## Languages

The whole site (public pages, sign-in, student area and instructor dashboard) is available
in English and Somali. Visitors switch
language in the page footer. The Somali texts are in `locale/so/LC_MESSAGES/django.po`;
after editing that file run `python manage.py compilemessages` (needs GNU gettext).
"# My_Elearning" 
