from django.contrib.auth.backends import ModelBackend


class LocalBackend(ModelBackend):
    """Login and password of the kernel's admin user; inactive accounts are refused."""
