"""
Directory Browser for AgenticGram
Provides interactive directory navigation through Telegram inline keyboards.
"""

import os
import base64
from pathlib import Path
from typing import List, Tuple, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class DirectoryBrowser:
    """Handles directory navigation and inline keyboard generation."""
    
    def __init__(
        self,
        start_dir: str = None,
        allowed_base_dirs: List[str] = None,
        blocked_dirs: List[str] = None,
        max_dirs_per_page: int = 8
    ):
        """
        Initialize directory browser.
        
        Args:
            start_dir: Default starting directory (defaults to user home)
            allowed_base_dirs: List of allowed base directories
            blocked_dirs: List of blocked system directories
            max_dirs_per_page: Maximum directories to show per page
        """
        self.start_dir = Path(start_dir or Path.home()).resolve()
        self.max_dirs_per_page = max_dirs_per_page
        
        # Default allowed directories
        if allowed_base_dirs is None:
            allowed_base_dirs = [
                str(Path.home()),
                "/home",
                "/opt",
                "/srv",
                "/var/www"
            ]
        self.allowed_base_dirs = [Path(d).resolve() for d in allowed_base_dirs]
        
        # Default blocked directories
        if blocked_dirs is None:
            blocked_dirs = [
                "/etc",
                "/sys",
                "/proc",
                "/root",
                "/boot",
                "/dev",
                "/run",
                "/tmp"
            ]
        self.blocked_dirs = [Path(d).resolve() for d in blocked_dirs]
    
    def is_safe_directory(self, path: str) -> Tuple[bool, str]:
        """
        Check if directory is safe to access.
        
        Args:
            path: Directory path to check
            
        Returns:
            Tuple of (is_safe, error_message)
        """
        try:
            resolved_path = Path(path).resolve()
            
            # Check if path exists and is a directory
            if not resolved_path.exists():
                return False, "Directory does not exist"
            
            if not resolved_path.is_dir():
                return False, "Path is not a directory"
            
            # Check if in blocked directories
            for blocked in self.blocked_dirs:
                try:
                    resolved_path.relative_to(blocked)
                    return False, f"Access to {blocked} is restricted"
                except ValueError:
                    continue
            
            # Check if in allowed base directories
            is_allowed = False
            for allowed in self.allowed_base_dirs:
                try:
                    resolved_path.relative_to(allowed)
                    is_allowed = True
                    break
                except ValueError:
                    continue
            
            if not is_allowed:
                return False, "Directory is outside allowed paths"
            
            # Check read permissions
            if not os.access(resolved_path, os.R_OK):
                return False, "No read permission"
            
            return True, ""
            
        except Exception as e:
            return False, f"Error checking directory: {str(e)}"
    
    def list_directories(self, path: str, page: int = 0) -> Tuple[List[Path], bool, bool]:
        """
        List subdirectories in a path with pagination.
        
        Args:
            path: Directory path to list
            page: Page number (0-indexed)
            
        Returns:
            Tuple of (directories, has_prev_page, has_next_page)
        """
        try:
            resolved_path = Path(path).resolve()
            
            # Get all subdirectories
            all_dirs = sorted([
                d for d in resolved_path.iterdir()
                if d.is_dir() and not d.name.startswith('.')
            ], key=lambda x: x.name.lower())
            
            # Paginate
            start_idx = page * self.max_dirs_per_page
            end_idx = start_idx + self.max_dirs_per_page
            
            page_dirs = all_dirs[start_idx:end_idx]
            has_prev = page > 0
            has_next = end_idx < len(all_dirs)
            
            return page_dirs, has_prev, has_next
            
        except PermissionError:
            return [], False, False
        except Exception:
            return [], False, False
    
    def get_parent_directory(self, path: str) -> Optional[str]:
        """
        Get parent directory path.
        
        Args:
            path: Current directory path
            
        Returns:
            Parent directory path or None if at root of allowed paths
        """
        try:
            resolved_path = Path(path).resolve()
            parent = resolved_path.parent
            
            # Check if parent is safe
            is_safe, _ = self.is_safe_directory(str(parent))
            if is_safe and parent != resolved_path:
                return str(parent)
            
            return None
            
        except Exception:
            return None
    
    def format_directory_path(self, path: str, max_length: int = 40) -> str:
        """
        Format directory path for display.
        
        Args:
            path: Directory path
            max_length: Maximum display length
            
        Returns:
            Formatted path string
        """
        try:
            resolved_path = Path(path).resolve()
            path_str = str(resolved_path)
            
            # Replace home directory with ~
            home = str(Path.home())
            if path_str.startswith(home):
                path_str = "~" + path_str[len(home):]
            
            # Truncate if too long
            if len(path_str) > max_length:
                path_str = "..." + path_str[-(max_length-3):]
            
            return path_str
            
        except Exception:
            return path
    
    @staticmethod
    def encode_path(path: str) -> str:
        """
        Encode path for callback data.
        
        Args:
            path: Directory path
            
        Returns:
            Base64 encoded path
        """
        return base64.urlsafe_b64encode(path.encode()).decode()
    
    @staticmethod
    def decode_path(encoded: str) -> str:
        """
        Decode path from callback data.
        
        Args:
            encoded: Base64 encoded path
            
        Returns:
            Decoded directory path
        """
        return base64.urlsafe_b64decode(encoded.encode()).decode()
    
    def create_navigation_keyboard(
        self,
        current_path: str,
        page: int = 0
    ) -> InlineKeyboardMarkup:
        """
        Create inline keyboard for directory navigation.
        
        Args:
            current_path: Current directory path
            page: Current page number
            
        Returns:
            InlineKeyboardMarkup for Telegram
        """
        keyboard = []
        
        # Get directories
        directories, has_prev, has_next = self.list_directories(current_path, page)
        
        # Add directory buttons (2 per row)
        for i in range(0, len(directories), 2):
            row = []
            for j in range(2):
                if i + j < len(directories):
                    dir_path = directories[i + j]
                    dir_name = dir_path.name
                    
                    # Truncate long names
                    if len(dir_name) > 20:
                        dir_name = dir_name[:17] + "..."
                    
                    encoded_path = self.encode_path(str(dir_path))
                    row.append(
                        InlineKeyboardButton(
                            f"📁 {dir_name}",
                            callback_data=f"dir_open_{encoded_path}"
                        )
                    )
            keyboard.append(row)
        
        # Pagination buttons
        if has_prev or has_next:
            pagination_row = []
            if has_prev:
                encoded_path = self.encode_path(current_path)
                pagination_row.append(
                    InlineKeyboardButton(
                        "⬅️ Previous",
                        callback_data=f"dir_page_{encoded_path}_{page-1}"
                    )
                )
            if has_next:
                encoded_path = self.encode_path(current_path)
                pagination_row.append(
                    InlineKeyboardButton(
                        "➡️ Next",
                        callback_data=f"dir_page_{encoded_path}_{page+1}"
                    )
                )
            keyboard.append(pagination_row)
        
        # Navigation buttons
        nav_row = []
        
        # Go up button
        parent = self.get_parent_directory(current_path)
        if parent:
            encoded_parent = self.encode_path(parent)
            nav_row.append(
                InlineKeyboardButton(
                    "⬆️ Go Up",
                    callback_data=f"dir_up_{encoded_parent}"
                )
            )
        
        keyboard.append(nav_row)
        
        # Action buttons
        action_row = []
        encoded_current = self.encode_path(current_path)
        
        action_row.append(
            InlineKeyboardButton(
                "✅ Select This Folder",
                callback_data=f"dir_select_{encoded_current}"
            )
        )
        action_row.append(
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="dir_cancel"
            )
        )
        
        keyboard.append(action_row)
        
        return InlineKeyboardMarkup(keyboard)
    
    def get_directory_info(self, path: str) -> str:
        """
        Get formatted directory information.
        
        Args:
            path: Directory path
            
        Returns:
            Formatted info string
        """
        try:
            resolved_path = Path(path).resolve()
            
            # Count subdirectories
            subdirs = sum(1 for d in resolved_path.iterdir() if d.is_dir() and not d.name.startswith('.'))
            
            # Check permissions
            can_read = os.access(resolved_path, os.R_OK)
            can_write = os.access(resolved_path, os.W_OK)
            
            permissions = []
            if can_read:
                permissions.append("Read")
            if can_write:
                permissions.append("Write")
            
            info = f"📂 **Current Directory**\n\n"
            info += f"Path: `{self.format_directory_path(str(resolved_path), 60)}`\n"
            info += f"Subdirectories: {subdirs}\n"
            info += f"Permissions: {', '.join(permissions) if permissions else 'None'}\n"
            
            return info
            
        except Exception as e:
            return f"Error getting directory info: {str(e)}"
