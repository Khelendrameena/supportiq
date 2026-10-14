"""Auth serializers: registration and tenant-aware JWT issuance."""
from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from tenants.models import Tenant

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    """Creates a tenant (by slug) and its first admin user in one call.

    Public endpoint — this is how a new customer signs up.
    """

    tenant_name = serializers.CharField(max_length=200)
    tenant_slug = serializers.SlugField(max_length=100)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_tenant_slug(self, value):
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError("tenant slug already taken")
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("email already registered")
        return value

    def create(self, validated_data):
        tenant = Tenant.objects.create(
            name=validated_data["tenant_name"], slug=validated_data["tenant_slug"]
        )
        user = User.objects.create_user(
            username=validated_data["email"],
            email=validated_data["email"],
            password=validated_data["password"],
            tenant=tenant,
            is_tenant_admin=True,
        )
        return user


class TenantTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds the tenant_id claim so the middleware can scope every request."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        if user.tenant_id:
            token["tenant_id"] = str(user.tenant_id)
        token["is_tenant_admin"] = bool(user.is_tenant_admin)
        return token
