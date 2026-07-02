"""
Filesystem ownership and permissions: all_owned_by_user, verify_ownership_and_permissions, set_ownership_and_permissions_sudo.
"""

import os
import logging
import subprocess
import pwd
import grp
from pathlib import Path


logger = logging.getLogger(__name__)


class FilesystemOwnershipMixin:
    """Mixin providing ownership check and sudo-compatible fix for FileSystemHandler."""

    @staticmethod
    def all_owned_by_user(path: Path) -> bool:
        """Return True if all files and directories under path are owned by the current user."""
        uid = os.getuid()
        gids = set([os.getgid()] + os.getgroups())
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                full_path = os.path.join(root, name)
                try:
                    stat = os.stat(full_path)
                    if stat.st_uid != uid or stat.st_gid not in gids:
                        return False
                except Exception:
                    return False
        return True

    @staticmethod
    def verify_ownership_and_permissions(path: Path) -> tuple:
        """
        Verify and fix ownership/permissions for modlist directory.
        Returns (success, error_message).
        """
        from jackify.backend.handlers.validation_handler import ValidationHandler
        if ValidationHandler().is_dangerous_directory(path):
            logger.error("Refusing to modify permissions on dangerous path: %s", path)
            return False, f"Refusing to modify permissions on '{path}': system or user root directory."

        if not path.exists():
            logger.error("Path does not exist: %s", path)
            return False, f"Path does not exist: {path}"

        if not FilesystemOwnershipMixin.all_owned_by_user(path):
            try:
                user_name = pwd.getpwuid(os.geteuid()).pw_name
                group_name = grp.getgrgid(os.getgid()).gr_name
            except KeyError:
                logger.error("Could not determine current user or group name.")
                return False, "Could not determine current user or group name."

            logger.error("Ownership issue detected: Some files in %s are not owned by %s", path, user_name)
            error_msg = (
                f"\nOwnership Issue Detected\n"
                f"Some files in the modlist directory are not owned by your user account.\n"
                f"This can happen if the modlist was copied from another location or installed by a different user.\n\n"
                f"To fix this, open a terminal and run:\n\n"
                f"  sudo chown -R {user_name}:{group_name} \"{path}\"\n"
                f"  sudo chmod -R 755 \"{path}\"\n\n"
                f"After running these commands, retry the configuration process."
            )
            return False, error_msg

        logger.info("Files in %s are owned by current user, verifying permissions...", path)
        if FilesystemOwnershipMixin._perms_already_ok(path):
            logger.info("Permissions already correct for %s, skipping chmod", path)
            return True, ""
        try:
            result = subprocess.run(
                ['chmod', '-R', '755', str(path)],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                logger.info("Permissions set successfully for %s", path)
                return True, ""
            logger.warning("chmod returned non-zero but we'll continue: %s", result.stderr)
            return True, ""
        except Exception as e:
            logger.warning("Error running chmod: %s, continuing anyway", e)
            return True, ""

    @staticmethod
    def _perms_already_ok(path: Path) -> bool:
        """Return True if every entry under path already has mode 0o755."""
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                full = os.path.join(root, name)
                try:
                    if os.stat(full).st_mode & 0o777 != 0o755:
                        return False
                except Exception:
                    return False
        return True

    @staticmethod
    def set_ownership_and_permissions_sudo(path: Path, status_callback=None) -> bool:
        """Deprecated: use verify_ownership_and_permissions() instead. Kept for backwards compatibility."""
        logger.warning("set_ownership_and_permissions_sudo() is deprecated - use verify_ownership_and_permissions()")
        success, error_msg = FilesystemOwnershipMixin.verify_ownership_and_permissions(path)
        if not success:
            logger.error("%s", error_msg)
        return success
