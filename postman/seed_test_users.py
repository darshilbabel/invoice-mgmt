"""Idempotent seed for the Postman API suite.

Ensures the three role accounts the collection logs in as exist with known
passwords. Run it from the backend directory:

    python manage.py shell < ../postman/seed_test_users.py

It is safe to re-run: every account goes through get_or_create and is then
updated in place. Nothing is ever deleted, and no invoice, customer or
transaction is touched. Passwords can be overridden with the environment
variables named below; the defaults match postman/invoice-mgmt.postman_environment.json.

These are local development credentials for a localhost-only training project.
Do not reuse them anywhere that matters.
"""

import os

from accounts.models import Role, User

ACCOUNTS = [
    ("test-admin@invoice.local", "Test Admin", Role.ADMIN, "PM_ADMIN_PASSWORD", "AdminPass123!"),
    ("test-staff@invoice.local", "Test Staff", Role.STAFF, "PM_STAFF_PASSWORD", "StaffPass123!"),
    ("test-viewer@invoice.local", "Test Viewer", Role.VIEWER, "PM_VIEWER_PASSWORD", "ViewerPass123!"),
]

before = User.objects.count()
print(f"users before: {before}")

for email, full_name, role, env_var, default_password in ACCOUNTS:
    password = os.environ.get(env_var, default_password)

    user, created = User.objects.get_or_create(
        email=email,
        defaults={"full_name": full_name, "role": role},
    )

    # Force the fields the suite depends on, whether the row is new or not — a
    # previous run (or a hand edit) may have left the role or active flag wrong.
    user.full_name = full_name
    user.role = role
    user.is_active = True
    # role drives API permissions; is_staff only gates /admin/. Set together for
    # ADMIN, per docs/domain.md.
    user.is_staff = role == Role.ADMIN
    user.set_password(password)
    user.save()

    print(f"  {'created' if created else 'updated'}  {email:28} {role}")

after = User.objects.count()
print(f"users after:  {after}  (+{after - before})")
print("seed complete")
