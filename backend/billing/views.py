from decimal import Decimal

from django.conf import settings
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce, Round
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import RolePermission, RoleScopedQuerysetMixin, scope_to_role

from .extraction import ExtractionError, extract_invoice_fields
from .filters import InvoiceFilter
from .models import Customer, Invoice, Transaction
from .serializers import (
    CustomerSerializer,
    InvoiceExtractionSerializer,
    InvoiceSerializer,
    TransactionDetailSerializer,
)

# Every PDF starts with these five bytes. Checked instead of trusting the
# extension or the client-supplied content type, both of which the client picks.
PDF_MAGIC = b"%PDF-"


def _bad_request(message):
    """The shape DRF uses for auth and permission errors, so the client's existing
    ApiError flattening renders it without a special case."""
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def _resolve_customer(guess):
    """Find the Customer an extracted supplier refers to, creating it if new.

    Returns (customer, created). Matching is email first — the one field on an
    invoice that is actually meant to be unique — then the printed name against
    both `name` and `company_name`, since suppliers put either on the page.

    NOTE: this creates rows. That reverses the rule this spec originally stated
    ("extraction never creates a Customer implicitly") and was chosen knowingly:
    the cost is that uploading a PDF and then discarding it still leaves a
    customer behind, and Customer is on_delete=PROTECT, so tidying up is manual.
    See open question 4 in docs/specs/2026-08-ocr-ingest.md.
    """
    if not guess or not guess.get("name"):
        return None, False

    email = (guess.get("email") or "").strip()
    if email:
        existing = Customer.objects.filter(email__iexact=email).first()
        if existing:
            return existing, False

    name = guess["name"].strip()
    existing = (
        Customer.objects.filter(name__iexact=name).first()
        or Customer.objects.filter(company_name__iexact=name).first()
    )
    if existing:
        return existing, False

    return (
        Customer.objects.create(
            name=name,
            email=email,
            billing_address=(guess.get("billing_address") or "").strip(),
        ),
        True,
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

    filterset_class = InvoiceFilter
    search_fields = ("customer__name", "customer__company_name", "notes")
    # `total` is deliberately absent: it is a Python property, not a column, so
    # the database cannot sort by it. See architecture.md section 4.
    ordering_fields = ("issue_date", "due_date", "created_at", "id")

    def perform_create(self, serializer):
        # Ownership comes from the request, never the payload.
        serializer.save(created_by=self.request.user)

    @action(
        detail=False,
        methods=["post"],
        url_path="extract",
        parser_classes=[MultiPartParser],
    )
    def extract(self, request):
        """POST /api/invoices/extract/ — read a PDF, return fields, save no invoice.

        An @action rather than its own path() so it inherits RolePermission (a
        POST, so VIEWER is refused for free) and so the router places it ahead of
        invoices/<pk>/ — registered after the router, `extract` would be swallowed
        by the detail route, whose default lookup regex matches any non-slash run.

        No invoice and no transaction is written here. The user reviews what comes
        back and the ordinary POST /api/invoices/ does the writing.
        """
        upload = request.FILES.get("file")
        if upload is None:
            return _bad_request("No file was uploaded. Send one PDF as `file`.")

        limit = settings.INVOICE_UPLOAD_MAX_BYTES
        if upload.size > limit:
            return _bad_request(
                f"{upload.name} is larger than the {limit // (1024 * 1024)} MB limit."
            )

        content = upload.read()
        if not content.startswith(PDF_MAGIC):
            return _bad_request(f"{upload.name} is not a PDF.")

        try:
            extracted = extract_invoice_fields(content, upload.name)
        except ExtractionError as exc:
            # A 400 with a readable message, never a 500 — the frontend renders
            # `detail` verbatim on its failure screen (conventions.md, Errors).
            return _bad_request(exc.message)

        customer, created = _resolve_customer(extracted.pop("customer_guess", None))

        payload = {
            **extracted,
            "customer": customer.pk if customer else None,
            "customer_created": created,
            "customer_detail": customer,
        }
        return Response(InvoiceExtractionSerializer(payload).data)


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
