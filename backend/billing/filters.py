import django_filters
from django.utils import timezone

from .models import Invoice


class InvoiceFilter(django_filters.FilterSet):
    """Query-param filters for /api/invoices/.

    `overdue` and `mine` are computed rather than plain field lookups, so they
    need methods. Everything in Meta.fields keeps the previous exact-match
    behaviour.
    """

    overdue = django_filters.BooleanFilter(
        method="filter_overdue",
        label="Only invoices past their due date",
    )
    mine = django_filters.BooleanFilter(
        method="filter_mine",
        label="Only invoices the requesting user created",
    )

    class Meta:
        model = Invoice
        fields = ("customer", "issue_date", "due_date")

    def filter_overdue(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(due_date__lt=timezone.localdate())

    def filter_mine(self, queryset, name, value):
        if not value:
            return queryset
        # For STAFF this is already the whole queryset (RoleScopedQuerysetMixin);
        # it only narrows anything for ADMIN and VIEWER.
        return queryset.filter(created_by=self.request.user)
