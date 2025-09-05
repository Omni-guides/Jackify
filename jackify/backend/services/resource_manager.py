#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resource Manager Module
Handles system resource limits for Jackify operations
"""

import resource
import logging
import os
from typing import Tuple, Optional

# Initialize logger
logger = logging.getLogger(__name__)


class ResourceManager:
    """
    Manages system resource limits for Jackify operations
    Focuses on file descriptor limits to resolve ulimit issues
    """
    
    # Target file descriptor limit based on successful user testing
    TARGET_FILE_DESCRIPTORS = 64556
    
    def __init__(self):
        """Initialize the resource manager"""
        self.original_limits = None
        self.current_limits = None
        self.target_achieved = False
        logger.debug("ResourceManager initialized")
    
    def get_current_file_descriptor_limits(self) -> Tuple[int, int]:
        """
        Get current file descriptor limits (soft, hard)
        
        Returns:
            tuple: (soft_limit, hard_limit)
        """
        try:
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            return soft, hard
        except Exception as e:
            logger.error(f"Error getting file descriptor limits: {e}")
            return 0, 0
    
    def increase_file_descriptor_limit(self, target_limit: Optional[int] = None) -> bool:
        """
        Increase file descriptor limit to target value
        
        Args:
            target_limit (int, optional): Target limit. Defaults to TARGET_FILE_DESCRIPTORS
            
        Returns:
            bool: True if limit was increased or already adequate, False if failed
        """
        if target_limit is None:
            target_limit = self.TARGET_FILE_DESCRIPTORS
        
        try:
            # Get current limits
            current_soft, current_hard = self.get_current_file_descriptor_limits()
            self.original_limits = (current_soft, current_hard)
            
            logger.info(f"Current file descriptor limits: soft={current_soft}, hard={current_hard}")
            
            # Check if we already have adequate limits
            if current_soft >= target_limit:
                logger.info(f"File descriptor limit already adequate: {current_soft} >= {target_limit}")
                self.target_achieved = True
                self.current_limits = (current_soft, current_hard)
                return True
            
            # Calculate new soft limit (can't exceed hard limit)
            new_soft = min(target_limit, current_hard)
            
            if new_soft <= current_soft:
                logger.warning(f"Cannot increase file descriptor limit: hard limit ({current_hard}) too low for target ({target_limit})")
                self.current_limits = (current_soft, current_hard)
                return False
            
            # Attempt to set new limits
            try:
                resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, current_hard))
                
                # Verify the change worked
                verify_soft, verify_hard = self.get_current_file_descriptor_limits()
                self.current_limits = (verify_soft, verify_hard)
                
                if verify_soft >= new_soft:
                    logger.info(f"Successfully increased file descriptor limit: {current_soft} -> {verify_soft}")
                    self.target_achieved = (verify_soft >= target_limit)
                    if not self.target_achieved:
                        logger.warning(f"Increased limit ({verify_soft}) is below target ({target_limit}) but above original ({current_soft})")
                    return True
                else:
                    logger.error(f"File descriptor limit increase failed verification: expected {new_soft}, got {verify_soft}")
                    return False
                    
            except (ValueError, OSError) as e:
                logger.error(f"Failed to set file descriptor limit: {e}")
                self.current_limits = (current_soft, current_hard)
                return False
                
        except Exception as e:
            logger.error(f"Error in increase_file_descriptor_limit: {e}")
            return False
    
    def get_limit_status(self) -> dict:
        """
        Get detailed status of file descriptor limits
        
        Returns:
            dict: Status information about limits
        """
        current_soft, current_hard = self.get_current_file_descriptor_limits()
        
        return {
            'current_soft': current_soft,
            'current_hard': current_hard,
            'original_limits': self.original_limits,
            'target_limit': self.TARGET_FILE_DESCRIPTORS,
            'target_achieved': self.target_achieved,
            'increase_needed': current_soft < self.TARGET_FILE_DESCRIPTORS,
            'can_increase': current_hard >= self.TARGET_FILE_DESCRIPTORS,
            'max_possible': current_hard
        }
    
    def get_manual_increase_instructions(self) -> dict:
        """
        Get distribution-specific instructions for manually increasing limits
        
        Returns:
            dict: Instructions organized by distribution/method
        """
        status = self.get_limit_status()
        target = self.TARGET_FILE_DESCRIPTORS
        
        # Detect distribution
        distro = self._detect_distribution()
        
        instructions = {
            'target_limit': target,
            'current_limit': status['current_soft'],
            'distribution': distro,
            'methods': {}
        }
        
        # Temporary increase (all distributions)
        instructions['methods']['temporary'] = {
            'title': 'Temporary Increase (Current Session Only)',
            'commands': [
                f'ulimit -n {target}',
                'jackify  # Re-run Jackify after setting ulimit'
            ],
            'note': 'This only affects the current terminal session'
        }
        
        # Permanent increase (varies by distribution)
        if distro in ['cachyos', 'arch', 'manjaro']:
            instructions['methods']['permanent'] = {
                'title': 'Permanent Increase (Arch-based Systems)',
                'commands': [
                    'sudo nano /etc/security/limits.conf',
                    f'# Add these lines to the file:',
                    f'* soft nofile {target}',
                    f'* hard nofile {target}',
                    '# Save file and reboot, or logout/login'
                ],
                'note': 'Requires root privileges and reboot/re-login'
            }
        elif distro in ['opensuse', 'suse']:
            instructions['methods']['permanent'] = {
                'title': 'Permanent Increase (openSUSE)',
                'commands': [
                    'sudo nano /etc/security/limits.conf',
                    f'# Add these lines to the file:',
                    f'* soft nofile {target}',
                    f'* hard nofile {target}',
                    '# Save file and reboot, or logout/login',
                    '# Alternative: Set in systemd service file'
                ],
                'note': 'May require additional systemd configuration on openSUSE'
            }
        else:
            instructions['methods']['permanent'] = {
                'title': 'Permanent Increase (Generic Linux)',
                'commands': [
                    'sudo nano /etc/security/limits.conf',
                    f'# Add these lines to the file:',
                    f'* soft nofile {target}',
                    f'* hard nofile {target}',
                    '# Save file and reboot, or logout/login'
                ],
                'note': 'Standard method for most Linux distributions'
            }
        
        return instructions
    
    def _detect_distribution(self) -> str:
        """
        Detect the Linux distribution
        
        Returns:
            str: Distribution identifier
        """
        try:
            # Check /etc/os-release
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release', 'r') as f:
                    content = f.read().lower()
                    
                if 'cachyos' in content:
                    return 'cachyos'
                elif 'arch' in content:
                    return 'arch'
                elif 'manjaro' in content:
                    return 'manjaro'
                elif 'opensuse' in content or 'suse' in content:
                    return 'opensuse'
                elif 'ubuntu' in content:
                    return 'ubuntu'
                elif 'debian' in content:
                    return 'debian'
                elif 'fedora' in content:
                    return 'fedora'
            
            # Fallback detection methods
            if os.path.exists('/etc/arch-release'):
                return 'arch'
            elif os.path.exists('/etc/SuSE-release'):
                return 'opensuse'
                
        except Exception as e:
            logger.warning(f"Could not detect distribution: {e}")
        
        return 'unknown'
    
    def is_too_many_files_error(self, error_message: str) -> bool:
        """
        Check if an error message indicates a 'too many open files' issue
        
        Args:
            error_message (str): Error message to check
            
        Returns:
            bool: True if error is related to file descriptor limits
        """
        if not error_message:
            return False
            
        error_lower = error_message.lower()
        indicators = [
            'too many open files',
            'too many files open',
            'cannot open',
            'emfile',  # errno 24
            'file descriptor',
            'ulimit',
            'resource temporarily unavailable'
        ]
        
        return any(indicator in error_lower for indicator in indicators)
    
    def apply_recommended_limits(self) -> bool:
        """
        Apply recommended resource limits for Jackify operations
        
        Returns:
            bool: True if limits were successfully applied
        """
        logger.info("Applying recommended resource limits for Jackify operations")
        
        # Focus on file descriptor limits as the primary issue
        success = self.increase_file_descriptor_limit()
        
        if success:
            status = self.get_limit_status()
            logger.info(f"Resource limits applied successfully. Current file descriptors: {status['current_soft']}")
        else:
            logger.warning("Failed to apply optimal resource limits")
            
        return success
    
    def handle_too_many_files_error(self, error_message: str, context: str = "") -> dict:
        """
        Handle a 'too many open files' error by attempting to increase limits and providing guidance
        
        Args:
            error_message (str): The error message that triggered this handler
            context (str): Additional context about where the error occurred
            
        Returns:
            dict: Result of handling the error, including success status and guidance
        """
        logger.warning(f"Detected 'too many open files' error in {context}: {error_message}")
        
        result = {
            'error_detected': True,
            'error_message': error_message,
            'context': context,
            'auto_fix_attempted': False,
            'auto_fix_success': False,
            'manual_instructions': None,
            'recommendation': ''
        }
        
        # Check if this is actually a file descriptor limit error
        if not self.is_too_many_files_error(error_message):
            result['error_detected'] = False
            return result
        
        # Get current status
        status = self.get_limit_status()
        
        # Attempt automatic fix if we haven't already optimized
        if not self.target_achieved and status['can_increase']:
            logger.info("Attempting to automatically increase file descriptor limits...")
            result['auto_fix_attempted'] = True
            
            success = self.increase_file_descriptor_limit()
            result['auto_fix_success'] = success
            
            if success:
                new_status = self.get_limit_status()
                result['recommendation'] = f"File descriptor limit increased to {new_status['current_soft']}. Please retry the operation."
                logger.info(f"Successfully increased file descriptor limit to {new_status['current_soft']}")
            else:
                result['recommendation'] = "Automatic limit increase failed. Manual intervention required."
                logger.warning("Automatic file descriptor limit increase failed")
        else:
            result['recommendation'] = "File descriptor limits already at maximum or cannot be increased automatically."
        
        # Always provide manual instructions as fallback
        result['manual_instructions'] = self.get_manual_increase_instructions()
        
        return result
    
    def show_guidance_dialog(self, parent=None):
        """
        Show the ulimit guidance dialog (GUI only)
        
        Args:
            parent: Parent widget for the dialog
            
        Returns:
            Dialog result or None if not in GUI mode
        """
        try:
            # Only available in GUI mode
            from jackify.frontends.gui.dialogs.ulimit_guidance_dialog import show_ulimit_guidance
            return show_ulimit_guidance(parent, self)
        except ImportError:
            logger.debug("GUI ulimit guidance dialog not available (likely CLI mode)")
            return None


# Convenience functions for easy use
def ensure_adequate_file_descriptor_limits() -> bool:
    """
    Convenience function to ensure adequate file descriptor limits
    
    Returns:
        bool: True if limits are adequate or were successfully increased
    """
    manager = ResourceManager()
    return manager.apply_recommended_limits()


def handle_file_descriptor_error(error_message: str, context: str = "") -> dict:
    """
    Convenience function to handle file descriptor limit errors
    
    Args:
        error_message (str): The error message that triggered this handler
        context (str): Additional context about where the error occurred
        
    Returns:
        dict: Result of handling the error, including success status and guidance
    """
    manager = ResourceManager()
    return manager.handle_too_many_files_error(error_message, context)


# Module-level testing
if __name__ == '__main__':
    # Configure logging for testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    print("Testing ResourceManager...")
    
    manager = ResourceManager()
    
    # Show current status
    status = manager.get_limit_status()
    print(f"\nCurrent Status:")
    print(f"  Current soft limit: {status['current_soft']}")
    print(f"  Current hard limit: {status['current_hard']}")
    print(f"  Target limit: {status['target_limit']}")
    print(f"  Increase needed: {status['increase_needed']}")
    print(f"  Can increase: {status['can_increase']}")
    
    # Test limit increase
    print(f"\nAttempting to increase limits...")
    success = manager.apply_recommended_limits()
    print(f"Success: {success}")
    
    # Show final status
    final_status = manager.get_limit_status()
    print(f"\nFinal Status:")
    print(f"  Current soft limit: {final_status['current_soft']}")
    print(f"  Target achieved: {final_status['target_achieved']}")
    
    # Test manual instructions
    instructions = manager.get_manual_increase_instructions()
    print(f"\nDetected distribution: {instructions['distribution']}")
    print(f"Manual increase available if needed")
    
    print("\nTesting completed successfully!")