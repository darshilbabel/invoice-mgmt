"""Project-wide DRF exception handling."""

from collections import Counter

from django.db.models import ProtectedError
from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler as drf_exception_handler


def _protected_detail(exc):
    """Readable message naming what is still referencing the row."""
    counts = Counter(obj._meta.verbose_name for obj in exc.protected_objects)
    parts = ", ".join(
        f"{n} {name}{'' if n == 1 else 's'}" for name, n in sorted(counts.items())
    )
    # Phrased passively so the verb agrees for both "1 invoice" and "2 invoices".
    return f"Cannot delete this record because it is referenced by {parts}."


def api_exception_handler(exc, context):
    """Turn ProtectedError into a 400 instead of an unhandled 500.

    Handled centrally rather than in each viewset's perform_destroy, so every
    on_delete=PROTECT relationship — current and future — is covered by default.
    See architecture.md section 3.5.
    """
    if isinstance(exc, ProtectedError):
        exc = ValidationError({"detail": _protected_detail(exc)})
    return drf_exception_handler(exc, context)
