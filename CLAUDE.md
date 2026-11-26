# CLAUDE.md
# E-LEARNING PLATFORM – DEVELOPMENT RULES

## 1. PROJECT ARCHITECTURE

This project uses:

- Django
- Django Templates
- Bootstrap 5
- Vanilla JavaScript
- SQLite (development and testing; PostgreSQL will be introduced later for production deployment)
- YouTube Embed

This is a simple, traditional Django application.

Do not introduce React, Node.js, a separate frontend application, REST API architecture, or unnecessary technologies.

The approved Django applications are:

- accounts
- courses
- learning
- payments
- core

Do not create additional Django applications without explicit approval.

## 2. MOST IMPORTANT RULE: KEEP CODE SIMPLE

Code readability is more important than architectural sophistication.

Every developer must be able to understand the code without studying complicated abstractions.

Mandatory rules:

1. Write short, readable and straightforward code.
2. Prefer simple solutions over clever solutions.
3. Do not over-engineer.
4. Do not create unnecessary classes.
5. Do not create unnecessary functions.
6. Do not create unnecessary helper files.
7. Do not create unnecessary folders.
8. Do not duplicate existing functionality.
9. Avoid deeply nested logic.
10. Avoid unnecessarily long files and complicated conditional structures.

Use Django's normal functionality whenever possible.

## 3. STRICT FILE STRUCTURE

The approved project structure must remain unchanged.

Before implementing any feature:

1. Inspect the existing project.
2. Identify the existing files responsible for that feature.
3. Explain which files need modification.
4. Reuse existing files whenever possible.
5. Do not create new files without a clear technical reason.

Never rename, move, delete or reorganize existing files without explicit approval.

Do not create multiple files for a feature that can reasonably be implemented in existing files.

## 4. BACKEND RULES

Follow these responsibilities:

- models.py: Database models.
- views.py: Request handling and business logic.
- forms.py: Form handling and validation.
- urls.py: URL routing.
- admin.py: Django administration.
- tests.py: Automated tests.

Use Django function-based views by default because they are straightforward to read.

Use Django model classes where required.

Do not introduce unnecessary service layers, repositories, factories, managers, adapters or generic helper systems.

Do not create a complicated architecture around simple database operations.

Keep business logic close to the feature that owns it.

## 5. FRONTEND RULES

Use:

- Django HTML templates.
- Bootstrap 5.
- Vanilla JavaScript.
- One shared base.html.
- Reusable template includes only when genuinely useful.

Do not introduce React, Vue, Angular, Redux or frontend build systems.

Keep HTML readable and organized.

Do not put large amounts of JavaScript inside HTML templates.

Keep custom CSS in static/css/style.css.

Keep shared JavaScript in static/js/app.js.

Do not create separate CSS and JavaScript files for every page unless there is a real need.

## 6. DATABASE RULES

Every model must have a clear purpose.

Before creating a model:

1. Inspect existing models.
2. Check whether the required information already exists.
3. Reuse existing relationships when appropriate.
4. Avoid duplicate fields and duplicate tables.

Use proper foreign keys and database constraints.

Never delete existing migrations.

Never reset the database.

Never modify existing production data to simplify development.

Before changing a model, explain the database impact.

## 7. FEATURE DEVELOPMENT WORKFLOW

For every new feature:

STEP 1: Inspect the existing implementation.

STEP 2: Identify the exact files involved.

STEP 3: Explain the implementation plan briefly.

STEP 4: Modify only necessary files.

STEP 5: Follow the approved architecture.

STEP 6: Run relevant tests.

STEP 7: Report the results.

Do not rewrite unrelated parts of the application.

Do not refactor working code unless explicitly requested or necessary for the feature.

## 8. SECURITY

Always enforce:

- Authentication.
- Role-based permissions.
- Instructor ownership of courses.
- Student ownership of learning records.
- Payment verification on the server.
- CSRF protection.
- Secure password handling.
- Input validation.

Never trust frontend permissions or payment success messages.

Never expose private course content to unauthorized students.

## 9. CODE QUALITY

Code must be:

- Easy to read.
- Easy to understand.
- Easy to modify.
- Easy to test.
- Consistent with existing conventions.

Use meaningful variable names.

Avoid unnecessary comments that simply repeat the code.

Add comments when logic is important or not immediately obvious.

Do not write unnecessarily long documentation for simple functions.

## 10. FORBIDDEN BEHAVIOUR

Claude must NEVER:

- Redesign the entire project without permission.
- Generate dozens of unnecessary files.
- Create a new architecture for every feature.
- Introduce unnecessary design patterns.
- Duplicate existing models or views.
- Install unnecessary dependencies.
- Change unrelated files.
- Remove working functionality.
- Claim tests passed without running them.
- Hide errors instead of fixing them.
- Make architectural decisions without explaining them.

## 11. COMPLETION REPORT

After every task, report:

1. What was implemented.
2. Which files were modified.
3. Why each file was modified.
4. Whether new files were created and why.
5. Database changes, if any.
6. Tests actually executed.
7. Any remaining issues.

Keep reports short and factual.

## FINAL PRINCIPLE

Simplicity is a mandatory architectural requirement.

The objective is not to write the most code.

The objective is to build a professional, secure, maintainable e-learning platform with the smallest reasonable amount of understandable code.

A developer unfamiliar with this project must be able to locate a feature quickly, understand its implementation, and modify it without navigating unnecessary layers.

Never sacrifice maintainability for architectural complexity.