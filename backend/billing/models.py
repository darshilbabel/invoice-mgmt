from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")

from django.conf import settings
from django.db import models
from django.utils import timezone


class Customer(models.Model):
    """Who an invoice is billed to. See architecture.md section 3.2.

    Invoices reference this row live (FK with PROTECT), so editing a customer
    changes what past invoices display — there is no frozen snapshot.
    """

    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    company_name = models.CharField(max_length=200, blank=True)
    billing_address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Explicit ordering: DRF pagination over an unordered queryset returns
        # inconsistent rows across pages.
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} ({self.company_name})" if self.company_name else self.name


class Invoice(models.Model):
    """See architecture.md section 3.3.

    Carries no status, no stored invoice number and no stored total — the last
    of these is the load-bearing rule of the system (section 4).
    """

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="invoices",
        help_text="Owner. STAFF users only see invoices where this is themselves.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Newest first for the invoice list; `-id` breaks ties on same-day
        # invoices so pagination stays stable.
        ordering = ("-issue_date", "-id")

    def __str__(self):
        return f"{self.invoice_number} — {self.customer.name}"

    @property
    def invoice_number(self):
        """Derived from the PK, never stored. Empty until the row is saved."""
        return f"INV-{self.pk:05d}" if self.pk is not None else ""

    @property
    def total(self):
        """Computed from transactions, never stored. See architecture.md section 4.

        Sums line totals that are each already rounded to cents, which is how
        invoices are conventionally totalled (round per line, then add).

        Callers listing many invoices must use .prefetch_related("transactions")
        or this is an N+1.
        """
        return sum((t.line_total for t in self.transactions.all()), Decimal("0.00"))


class Transaction(models.Model):
    """An invoice line item. See architecture.md section 3.4.

    No tax and no discount — quantity x unit_price is the entire money model.
    """

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Decimal so partial units (2.5 hours) are billable.",
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Stable order so nested API output and the edit form keep line items
        # in the sequence they were entered.
        ordering = ("id",)

    def __str__(self):
        return f"{self.description} x {self.quantity}"

    @property
    def line_total(self):
        """Always exactly 2dp.

        Decimal multiplication adds exponents (2.5 * 100.00 -> 250.000), so the
        raw product's scale varies with its inputs. Money needs one canonical
        representation: the API serialises it as a string and the frontend never
        reformats it.
        """
        return (self.quantity * self.unit_price).quantize(CENTS, rounding=ROUND_HALF_UP)
