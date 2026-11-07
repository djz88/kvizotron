import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models


class PluginInstallation(models.Model):
    class Status(models.TextChoices):
        INSTALLED = "INSTALLED"
        INACTIVE = "INACTIVE"  # installed, but another provider of the capability is selected
        MISSING = "MISSING"

    plugin_id = models.CharField(max_length=200, primary_key=True)
    version = models.CharField(max_length=50)
    manifest_json = models.JSONField()
    enabled = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INSTALLED)


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    actor_type = models.CharField(max_length=20)
    actor_id = models.CharField(max_length=100, null=True, blank=True)
    action = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=50)
    entity_id = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    details_json = models.JSONField(default=dict)


class AdminUserManager(BaseUserManager):
    def create_admin(self, login: str, password: str) -> AdminUser:
        """Callers validate the password: `AdminUserForm` and `passwords.read_password`."""
        limit = self.model._meta.get_field("login").max_length
        if not login.strip() or len(login) > limit:
            raise ValueError(f"An admin login must have 1 to {limit} characters")
        user = self.model(login=login)
        user.set_password(password)
        user.save(using=self._db)
        return user


class AdminUser(AbstractBaseUser):
    """Shared by all auth providers. All admins are equal, so no permissions (ADR-0014)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    login = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AdminUserManager()

    USERNAME_FIELD = "login"

    class Meta:
        db_table = "admin_user"
