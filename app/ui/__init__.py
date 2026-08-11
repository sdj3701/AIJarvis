"""User-interface infrastructure shared by CLI and future resident UI."""

from app.ui.single_instance import AlreadyRunningError, SingleInstanceLock

__all__ = ["AlreadyRunningError", "SingleInstanceLock"]
