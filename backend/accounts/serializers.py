from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    """The identity payload returned by login and /api/auth/me/.

    Read-only: `role` is only writable through /api/users/ by an ADMIN, so a user
    can never escalate themselves. See architecture.md section 5.1.
    """

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role")
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    """Validates the shape of the credentials only; authentication happens in the
    view so a bad password can return 401 rather than a 400 validation error."""

    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )


class UserAdminSerializer(serializers.ModelSerializer):
    """Full user CRUD for /api/users/ — ADMIN only.

    Unlike UserSerializer above, `role` IS writable here: that endpoint is the
    only place a role may be set, and only an administrator can reach it.
    """

    password = serializers.CharField(write_only=True, required=False, style={"input_type": "password"})

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "role",
            "is_active",
            "is_staff",
            "password",
            "date_joined",
            "last_login",
        )
        read_only_fields = ("id", "date_joined", "last_login")

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError(
                {"password": "This field is required when creating a user."}
            )
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user
