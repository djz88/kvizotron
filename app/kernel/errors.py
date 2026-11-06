class StartupError(RuntimeError):
    """A deployment problem that must stop the application before it serves anything."""
