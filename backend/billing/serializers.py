from django.db import transaction as db_transaction
from rest_framework import serializers

from accounts.permissions import scope_to_role
from accounts.serializers import UserSerializer

from .models import Customer, Invoice, Transaction


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "id",
            "name",
            "email",
            "company_name",
            "billing_address",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class ExtractedLineSerializer(serializers.Serializer):
    """One line item as read off a PDF. Output only — nothing is saved from here."""

    description = serializers.CharField(allow_blank=True)
    # DecimalFields, not CharFields: this is what makes money leave as a quoted
    # 2dp string. See conventions.md, Money.
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2)


class InvoiceExtractionSerializer(serializers.Serializer):
    """The response of POST /api/invoices/extract/.

    Output only, and it persists nothing: the user reviews this, corrects it, and
    then the ordinary POST /api/invoices/ writes the invoice. The one exception is
    `customer`, which is a real row by the time this is rendered — see
    InvoiceViewSet.extract and open question 4 in docs/specs/2026-08-ocr-ingest.md.
    """

    customer = serializers.IntegerField(allow_null=True)
    customer_created = serializers.BooleanField()
    customer_detail = CustomerSerializer(allow_null=True)

    # Printed on the supplier's PDF. Shown for reference and then discarded —
    # Invoice.invoice_number is derived from the pk and has no column to take it.
    source_invoice_number = serializers.CharField(allow_null=True)
    issue_date = serializers.DateField(allow_null=True)
    due_date = serializers.DateField(allow_null=True)
    notes = serializers.CharField(allow_blank=True)
    transactions = ExtractedLineSerializer(many=True)

    # A cross-check against the sum of the rows above, never the invoice's total.
    # domain.md's rule is unaffected: the total is still computed from line items.
    printed_total = serializers.DecimalField(
        max_digits=14, decimal_places=2, allow_null=True
    )

    low_confidence = serializers.ListField(child=serializers.CharField())
    field_notes = serializers.DictField(child=serializers.CharField())
    page_count = serializers.IntegerField()


class TransactionSerializer(serializers.ModelSerializer):
    """Nested inside InvoiceSerializer. No `invoice` field — the parent supplies it."""

    line_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Transaction
        fields = ("id", "description", "quantity", "unit_price", "line_total")
        read_only_fields = ("id", "line_total")


class TransactionDetailSerializer(serializers.ModelSerializer):
    """Standalone /api/transactions/.

    Unlike the nested TransactionSerializer above, this one exposes `invoice`, so
    it has to enforce ownership itself.
    """

    line_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Transaction
        fields = ("id", "invoice", "description", "quantity", "unit_price", "line_total")
        read_only_fields = ("id", "line_total")

    def validate_invoice(self, invoice):
        # DRF builds `invoice` as a PrimaryKeyRelatedField spanning every invoice,
        # and RoleScopedQuerysetMixin narrows reads only. Without this check a
        # STAFF user could attach a line to an invoice they cannot even read.
        visible = scope_to_role(Invoice.objects.all(), self.context["request"].user)
        if not visible.filter(pk=invoice.pk).exists():
            # "Not found" rather than "forbidden", for the same reason detail
            # routes 404: do not confirm that the row exists.
            raise serializers.ValidationError("Invoice not found.")
        return invoice


class InvoiceSerializer(serializers.ModelSerializer):
    """Nested writable serializer — see architecture.md section 5.2.

    Writes accept `customer` as a primary key; reads return it expanded. Both use
    the same key, matching the documented contract.

    `total` and `invoice_number` are read-only: they are computed properties, not
    columns, and must never be settable by a client.
    """

    transactions = TransactionSerializer(many=True, required=False)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    invoice_number = serializers.CharField(read_only=True)

    class Meta:
        model = Invoice
        fields = (
            "id",
            "invoice_number",
            "customer",
            "issue_date",
            "due_date",
            "notes",
            "created_by",
            "total",
            "transactions",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "invoice_number",
            "created_by",
            "total",
            "created_at",
            "updated_at",
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Expand the relations on read only. select_related in the viewset keeps
        # this from costing a query per row.
        data["customer"] = CustomerSerializer(instance.customer).data
        data["created_by"] = UserSerializer(instance.created_by).data
        return data

    @db_transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("transactions", [])
        invoice = Invoice.objects.create(**validated_data)
        Transaction.objects.bulk_create(
            [Transaction(invoice=invoice, **line) for line in lines]
        )
        return invoice

    @db_transaction.atomic
    def update(self, instance, validated_data):
        """Replace-all: the payload's line items become the complete set.

        This churns Transaction primary keys on every save, which is documented
        in architecture.md section 5.2 — nothing may hold a long-lived reference
        to a line-item id. Omitting `transactions` entirely (a PATCH) leaves the
        existing lines untouched.
        """
        lines = validated_data.pop("transactions", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if lines is not None:
            instance.transactions.all().delete()
            Transaction.objects.bulk_create(
                [Transaction(invoice=instance, **line) for line in lines]
            )
        return instance
