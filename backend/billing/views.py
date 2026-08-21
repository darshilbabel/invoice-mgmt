from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce, Round
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import RolePermission, RoleScopedQuerysetMixin, scope_to_role

from .models import Customer, Invoice, Transaction
from .serializers import (
    CustomerSerializer,
    InvoiceSerializer,
    TransactionDetailSerializer,
)

# Money crosses the wire as a 2dp string everywhere (architecture.md section 7).
# A bare Decimal in a Response dict bypasses DRF's COERCE_DECIMAL_TO_STRING and
# renders as a JSON number, so the dashboard total goes through a real field.
MONEY = serializers.DecimalField(max_digits=14, decimal_places=2)


class CustomerViewSet(viewsets.ModelViewSet):
    """/api/customers/ — readable by every role, writable by ADMIN and STAFF.

    Deleting a customer that has invoices raises ProtectedError, which
    config.exceptions.api_exception_handler converts to a 400.
    """

    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [RolePermission]

    filterset_fields = ("company_name",)
    search_fields = ("name", "company_name", "email")
    ordering_fields = ("name", "company_name", "created_at")


class InvoiceViewSet(RoleScopedQuerysetMixin, viewsets.ModelViewSet):
    """/api/invoices/ — nested writes, role-scoped reads.

    STAFF sees only invoices it created (RoleScopedQuerysetMixin filters on
    `created_by`); ADMIN and VIEWER see all.
    """

    # prefetch_related is what makes Invoice.total cost 2 queries for N invoices
    # instead of N+1 — see architecture.md section 4.
    queryset = (
        Invoice.objects.select_related("customer", "created_by")
        .prefetch_related("transactions")
    )
    serializer_class = InvoiceSerializer
    permission_classes = [RolePermission]

    filterset_fields = ("customer", "issue_date", "due_date")
    search_fields = ("customer__name", "customer__company_name", "notes")
    # `total` is deliberately absent: it is a Python property, not a column, so
    # the database cannot sort by it. See architecture.md section 4.
    ordering_fields = ("issue_date", "due_date", "created_at", "id")

    def perform_create(self, serializer):
        # Ownership comes from the request, never the payload.
        serializer.save(created_by=self.request.user)


class TransactionViewSet(RoleScopedQuerysetMixin, viewsets.ModelViewSet):
    """/api/transactions/ — standalone line-item CRUD.

    Registered to satisfy the PRD's "CRUD endpoints for all models". The React app
    does not use it; it writes line items through the nested invoice payload
    (architecture.md section 5.2).
    """

    queryset = Transaction.objects.select_related("invoice", "invoice__created_by")
    serializer_class = TransactionDetailSerializer
    permission_classes = [RolePermission]
    owner_field = "invoice__created_by"  # scoped through the parent invoice

    filterset_fields = ("invoice",)
    search_fields = ("description",)
    # `line_total` is absent for the same reason `total` is on invoices: it is a
    # Python property, not a column.
    ordering_fields = ("id", "created_at", "quantity", "unit_price")


class DashboardView(APIView):
    """GET /api/dashboard/ — see architecture.md section 5.3.

    Scoped by role identically to /api/invoices/, via the same scope_to_role
    function the viewsets use.
    """

    def get(self, request):
        invoices = scope_to_role(Invoice.objects.all(), request.user)

        # Round each line INSIDE the Sum so this agrees with Invoice.total, which
        # quantizes every line_total before adding. A bare Sum(quantity * price)
        # sums raw 4dp products and can differ by a cent. architecture.md sec. 4.
        line_total = Round(
            ExpressionWrapper(
                F("transactions__quantity") * F("transactions__unit_price"),
                output_field=DecimalField(max_digits=14, decimal_places=4),
            ),
            2,
        )
        grand_total = invoices.aggregate(
            value=Coalesce(
                Sum(line_total),
                Decimal("0.00"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )["value"]

        recent = (
            invoices.select_related("customer", "created_by")
            .prefetch_related("transactions")[:5]
        )

        return Response(
            {
                # Separate counts rather than one aggregate(): joining transactions
                # fans out invoice rows, so a combined Count("id") would overcount.
                "invoice_count": invoices.count(),
                "grand_total": MONEY.to_representation(grand_total),
                "overdue_count": invoices.filter(
                    due_date__lt=timezone.localdate()
                ).count(),
                # Deliberately unscoped — customers have no owner, and
                # /api/customers/ is readable by every role.
                "customer_count": Customer.objects.count(),
                "recent_invoices": InvoiceSerializer(
                    recent, many=True, context={"request": request}
                ).data,
            }
        )
