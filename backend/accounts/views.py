from django.contrib.auth import authenticate
from rest_framework import status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .permissions import IsAdminRole
from .serializers import LoginSerializer, UserAdminSerializer, UserSerializer


class LoginView(APIView):
    """POST /api/auth/login/ -> {token, user}.

    `authentication_classes` is deliberately left at the default. DRF downgrades
    a 401 to 403 when a view exposes no authenticator (it has no
    `WWW-Authenticate` header to send), and we want a wrong password to be a 401.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)  # 400 on a malformed body

        user = authenticate(
            request=request,
            username=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            # Same message for unknown email and wrong password — do not leak
            # which accounts exist. Inactive users land here too, since
            # ModelBackend refuses them.
            raise AuthenticationFailed("Invalid email or password.")

        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class LogoutView(APIView):
    """POST /api/auth/logout/ — deletes the token server-side, so logging out is
    a real revocation rather than the client forgetting the key."""

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """GET /api/auth/me/ -> the current user's identity and role."""

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class UserViewSet(viewsets.ModelViewSet):
    """/api/users/ — full CRUD, ADMIN only. There is no public registration.

    Deleting a user who owns invoices raises ProtectedError (Invoice.created_by
    is PROTECT), which the project exception handler turns into a 400.
    """

    queryset = User.objects.all()
    serializer_class = UserAdminSerializer
    permission_classes = [IsAdminRole]

    filterset_fields = ("role", "is_active", "is_staff")
    search_fields = ("email", "full_name")
    ordering_fields = ("email", "date_joined")
