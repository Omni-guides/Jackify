#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Operation Lock Mixin
Provides reliable button state management for GUI operations
"""

from contextlib import contextmanager


class OperationLockMixin:
    """
    Mixin that provides reliable button state management.
    Ensures controls are always re-enabled after operations, even if exceptions occur.
    """

    def operation_lock(self):
        """
        Context manager that ensures controls are always re-enabled after operations.

        Usage:
            with self.operation_lock():
                # Perform operation that might fail
                risky_operation()
            # Controls are guaranteed to be re-enabled here
        """
        @contextmanager
        def lock_manager():
            try:
                if hasattr(self, '_disable_controls_during_operation'):
                    self._disable_controls_during_operation()
                yield
            finally:
                # Ensure controls are re-enabled even if exceptions occur
                if hasattr(self, '_enable_controls_after_operation'):
                    self._enable_controls_after_operation()

        return lock_manager()

    def safe_operation(self, operation_func, *args, **kwargs):
        """
        Execute an operation with automatic button state management.

        Args:
            operation_func: Function to execute
            *args, **kwargs: Arguments to pass to operation_func

        Returns:
            Result of operation_func or None if exception occurred
        """
        try:
            with self.operation_lock():
                return operation_func(*args, **kwargs)
        except Exception as e:
            # Log the error but don't re-raise - controls are already re-enabled
            if hasattr(self, 'logger'):
                self.logger.error(f"Operation failed: {e}", exc_info=True)
            # Could also show user error dialog here if needed
            return None

    def reset_screen_to_defaults(self):
        """
        Reset the screen to default state when navigating back from main menu.
        Override this method in subclasses to implement screen-specific reset logic.
        """
        pass  # Default implementation does nothing - subclasses should override