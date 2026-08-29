"""Shared install-request validation for both GUI and CLI frontends.

Each frontend keeps its own presentation (dialogs vs print/input prompts); this module
only decides what to check and how severe each finding is. Update-vs-new detection lives
in backend/services/update_detection.py (shared by both frontends already); the CLF3
download-URL gate lives at each frontend's modlist-selection point (both call
backend/services/modlist_download_url.py::get_modlist_download_url()) rather than here,
since it only applies to one specific selection path, not every install request.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

VR_GAME_TYPES = ('skyrimvr', 'fallout4vr')

_REQUIRED_FIELD_LABELS = {
    'modlist_name': 'Modlist Name',
    'install_dir': 'Install Directory',
    'download_dir': 'Download Directory',
    'nexus_api_key': 'Nexus API Key',
    'game_type': 'Game Type',
}


@dataclass
class ValidationIssue:
    code: str
    severity: str  # "error" | "warning"
    message: str
    field: Optional[str] = None


def validate_install_request(
    *,
    modlist_name: Optional[str] = None,
    install_dir: Optional[str] = None,
    download_dir: Optional[str] = None,
    nexus_api_key: Optional[str] = None,
    game_type: Optional[str] = None,
    fields_to_check: Optional[Set[str]] = None,
) -> List[ValidationIssue]:
    """Validate an install request. Returns a list of issues, empty if none found.

    `fields_to_check` restricts the missing-field check to a subset of
    _REQUIRED_FIELD_LABELS - useful for callers that only have some of the
    values available at their point in a multi-step validation flow. The
    directory-safety and game-support checks always run when their
    corresponding value is provided, regardless of this parameter.
    """
    issues: List[ValidationIssue] = []

    fields = {
        'modlist_name': modlist_name,
        'install_dir': install_dir,
        'download_dir': download_dir,
        'nexus_api_key': nexus_api_key,
        'game_type': game_type,
    }
    check_fields = fields_to_check if fields_to_check is not None else set(_REQUIRED_FIELD_LABELS)
    for field, value in fields.items():
        if field not in check_fields:
            continue
        if not value:
            issues.append(ValidationIssue(
                code='missing_field',
                severity='error',
                message=f"{_REQUIRED_FIELD_LABELS[field]} is required",
                field=field,
            ))

    if install_dir:
        from jackify.backend.handlers.validation_handler import ValidationHandler
        validation_handler = ValidationHandler()
        install_path = Path(install_dir)
        is_safe, reason = validation_handler.is_safe_install_directory(install_path)
        if not is_safe:
            severity = 'error' if validation_handler.is_dangerous_directory(install_path) else 'warning'
            code = 'dangerous_directory' if severity == 'error' else 'unsafe_directory'
            issues.append(ValidationIssue(code=code, severity=severity, message=reason, field='install_dir'))

    if game_type:
        from jackify.backend.handlers.wabbajack_parser import WabbajackParser
        if not WabbajackParser().is_supported_game(game_type):
            issues.append(ValidationIssue(
                code='unsupported_game',
                severity='warning',
                message=f"Game type '{game_type}' is not supported by Jackify's post-install configuration.",
                field='game_type',
            ))
        elif game_type in VR_GAME_TYPES:
            issues.append(ValidationIssue(
                code='vr_game',
                severity='warning',
                message=f"'{game_type}' is a VR game type; post-install configuration support is limited.",
                field='game_type',
            ))

    return issues
