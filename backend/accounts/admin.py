from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from .models import User


class UserCreateForm(AdminUserCreationForm):
    """Django's admin create form, retargeted at email instead of username."""

    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("email", "full_name", "role")
        field_classes = {}  # drop the inherited UsernameField mapping


class UserUpdateForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"
        field_classes = {}


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Mandatory, not cosmetic: Django's default UserAdmin references `username`,
    which this model does not have, so /admin/ 500s without this. See
    architecture.md section 6.
    """

    form = UserUpdateForm
    add_form = UserCreateForm

    list_display = ("email", "full_name", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff", "is_superuser", "groups")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    # auto_now_add / auto_now fields are not editable; they need to be readonly
    # to appear in the fieldsets at all.
    readonly_fields = ("last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name",)}),
        (
            "Role and permissions",
            {
                "fields": (
                    "role",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
                "description": (
                    "`role` drives API permissions. `is_staff` grants access to "
                    "this admin site. Set them together for an admin."
                ),
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "full_name",
                    "role",
                    "usable_password",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
