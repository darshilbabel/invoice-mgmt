"""Both axes of the access rule in architecture.md section 5.1.

They are kept in one module deliberately: the read/write axis and the ownership
axis are halves of a single table, and splitting them invites one being updated
without the other.

    role    | list / retrieve | create | update / delete
    --------+-----------------+--------+----------------
    ADMIN   | all             | yes    | any
    STAFF   | own only        | yes    | own only
    VIEWER  | all             | no     | no
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Role


class RolePermission(BasePermission):
    """The read/write axis. VIEWER is read-only; ADMIN and STAFF may write.

    Ownership is *not* enforced here — RoleScopedQuerysetMixin narrows the
    queryset instead, so a STAFF user attempting to reach someone else's invoice
    gets a 404 rather than a 403. That is intentional: a 403 would confirm the
    row exists.
    """

    message = "Your role does not permit this action."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.role in (Role.ADMIN, Role.STAFF)


class IsAdminRole(BasePermission):
    """ADMIN only — used by /api/users/, which VIEWER cannot even read."""

    message = "Only administrators may perform this action."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == Role.ADMIN)


def scope_to_role(queryset, user, owner_field="created_by"):
    """The ownership axis, as a plain function.

    Lives outside the mixin so non-viewset code (the dashboard APIView) applies
    the identical rule instead of reimplementing the STAFF filter — this is the
    single most drift-prone line in the project.

    `owner_field` is the ORM path from the model to the owning user:
    "created_by" on Invoice, "invoice__created_by" on Transaction.
    """
    if user.is_authenticated and user.role == Role.STAFF:
        return queryset.filter(**{owner_field: user})
    return queryset


class RoleScopedQuerysetMixin:
    """The ownership axis for viewsets. STAFF sees only rows it owns.

    NOTE: this narrows READS only. A serializer exposing a writable relation to a
    scoped model must validate it separately — see TransactionDetailSerializer.
    """

    owner_field = "created_by"

    def get_queryset(self):
        return scope_to_role(super().get_queryset(), self.request.user, self.owner_field)
