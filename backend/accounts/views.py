"""Auth endpoints."""
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import RegisterSerializer, TenantTokenObtainPairSerializer


class TenantTokenObtainPairView(TokenObtainPairView):
    serializer_class = TenantTokenObtainPairSerializer


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        tokens = TenantTokenObtainPairSerializer.get_token(user)
        return Response(
            {
                "tenant": {"id": str(user.tenant_id), "slug": user.tenant.slug, "name": user.tenant.name},
                "user": {"id": user.id, "email": user.email},
                "access": str(tokens.access_token),
                "refresh": str(tokens),
            },
            status=status.HTTP_201_CREATED,
        )


class MeView(APIView):
    def get(self, request):
        u = request.user
        return Response(
            {
                "id": u.id,
                "email": u.email,
                "is_tenant_admin": u.is_tenant_admin,
                "tenant": {"id": str(u.tenant_id), "slug": u.tenant.slug, "name": u.tenant.name}
                if u.tenant_id
                else None,
            }
        )
