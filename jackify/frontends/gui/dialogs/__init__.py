"""
GUI Dialogs Package

Custom dialogs for the Jackify GUI application.
"""

from .completion_dialog import NextStepsDialog
from .success_dialog import SuccessDialog
from .verification_results_dialog import VerificationResultsDialog

__all__ = ['NextStepsDialog', 'SuccessDialog', 'VerificationResultsDialog']