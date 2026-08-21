from django.contrib import admin

from .models import Customer, Invoice, Transaction


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    # The admin is the only place customers are created — the React app has no
    # customer UI (architecture.md section 7), so search is worth the one line.
    search_fields = ("name", "company_name", "email")


admin.site.register(Invoice)
admin.site.register(Transaction)
