"""
Claude Code CLI Handler for AgenticGram.
Manages interaction with Claude Code CLI, including permission handling.
"""

import asyncio
import logging
import re
import uuid
from typing import Optional, Callable, Dict, Any
from datetime import datetime
from pathlib import Path

from .pty_handler import PTYHandler


logger = logging.getLogger(__name__)


class ClaudeHandler:
    """Handles Claude Code CLI execution and permission management."""
    
    def __init__(self, permission_callback: Optional[Callable] = None, claude_path: Optional[str] = None):
        """
        Initialize Claude Code handler.
        
        Args:
            permission_callback: Async callback function for permission requests
                                Signature: async def callback(action_type: str, details: dict) -> bool
            claude_path: Optional custom path to Claude CLI executable
        """
        self.permission_callback = permission_callback
        self.pending_permissions: Dict[str, asyncio.Future] = {}
        # Use custom path if provided, otherwise default to 'claude' command
        self.claude_path = claude_path or "claude"
        
        # Initialize PTY handler
        self.pty_handler = PTYHandler()
        
        logger.info(f"Claude handler initialized with path: {self.claude_path}")
    
    async def check_availability(self) -> bool:
        """
        Check if Claude Code CLI is available.
        
        Returns:
            True if available, False otherwise
        """
        try:
            logger.debug(f"Checking Claude CLI availability at: {self.claude_path}")
            
            process = await asyncio.create_subprocess_exec(
                self.claude_path, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                version = stdout.decode().strip()
                logger.info(f"Claude CLI is available: {version}")
                return True
            else:
                error = stderr.decode().strip()
                logger.warning(f"Claude CLI check failed: {error}")
                return False
        except FileNotFoundError as e:
            logger.error(f"Claude CLI not found at '{self.claude_path}': {e}")
            logger.error("Hint: Set CLAUDE_CODE_PATH environment variable or ensure 'claude' is in PATH")
            return False
        except Exception as e:
            logger.error(f"Error checking Claude CLI availability: {e}", exc_info=True)
            return False
    
    async def execute_command(
        self,
        instruction: str,
        work_dir: str,
        output_callback: Optional[Callable[[str], Any]] = None,
        timeout: int = 1800  # 30 minutes for long tasks
    ) -> Dict[str, Any]:
        """
        Execute a command via Claude Code CLI with PTY for full interactive support.
        
        Args:
            instruction: The instruction to send to Claude Code
            work_dir: Working directory for the command
            output_callback: Optional callback for streaming output
            timeout: Command timeout in seconds
            
        Returns:
            Dictionary with 'success', 'output', and optional 'error' keys
        """
        try:
            # Ensure working directory exists
            Path(work_dir).mkdir(parents=True, exist_ok=True)
            
            # Build command without session ID - Claude manages sessions automatically
            command = [
                self.claude_path,
                instruction
            ]
            
            logger.info(f"Executing Claude CLI with PTY in {work_dir}")
            
            # Execute with PTY
            result = await self.pty_handler.execute_with_pty(
                command=command,
                cwd=work_dir,
                prompt_callback=self._handle_interactive_prompt,
                output_callback=output_callback,
                timeout=timeout
            )
            
            if result["success"]:
                logger.info(f"Command completed successfully")
            else:
                logger.error(f"Command failed: {result.get('error', 'Unknown error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing Claude Code command: {e}", exc_info=True)
            return {
                "success": False,
                "output": "",
                "error": f"Unexpected error: {str(e)}"
            }
    
    async def _handle_interactive_prompt(self, prompt_text: str) -> str:
        """
        Handle interactive prompts from Claude CLI.
        
        Args:
            prompt_text: The prompt text (ANSI codes already stripped)
            
        Returns:
            Response to send to Claude (e.g., "1\n", "y\n", "n\n")
        """
        # Patterns for directory trust prompts
        trust_patterns = [
            "Yes, I trust this folder",
            "Is this a project you created",
            "Quick safety check",
            "trust this folder"
        ]
        
        # Check if it's a directory trust prompt
        if any(pattern in prompt_text for pattern in trust_patterns):
            logger.info("Auto-approving directory trust prompt")
            return "1\n"  # Select option 1 (Yes, I trust)
        
        # Check for yes/no prompts
        if any(indicator in prompt_text for indicator in ["(y/n)", "(yes/no)", "[Y/n]", "[y/N]"]):
            # Forward to permission callback
            if self.permission_callback:
                logger.info("Forwarding yes/no prompt to user via Telegram")
                try:
                    approved = await self.permission_callback("interactive_prompt", {
                        "description": prompt_text,
                        "prompt_type": "yes_no"
                    })
                    response = "y\n" if approved else "n\n"
                    logger.info(f"User {'approved' if approved else 'denied'} prompt")
                    return response
                except Exception as e:
                    logger.error(f"Error in permission callback: {e}", exc_info=True)
                    return "n\n"  # Default to deny on error
            else:
                logger.warning("No permission callback set, denying prompt")
                return "n\n"
        
        # Check for numbered menu options
        if re.search(r'^\s*\d+\.', prompt_text, re.MULTILINE):
            # It's a menu - extract options and forward to user
            if self.permission_callback:
                logger.info("Detected menu prompt, extracting options...")
                
                # Extract menu options using PTY handler
                menu_options = self.pty_handler._extract_menu_options(prompt_text)
                
                if menu_options:
                    logger.info(f"Found {len(menu_options)} menu options")
                    try:
                        # Send menu to Telegram with options as buttons
                        response_number = await self.permission_callback("menu_prompt", {
                            "description": prompt_text,
                            "prompt_type": "menu",
                            "options": menu_options
                        })
                        
                        # Response should be the option number
                        if response_number:
                            logger.info(f"User selected option {response_number}")
                            return f"{response_number}\n"
                        else:
                            logger.warning("No option selected, defaulting to 1")
                            return "1\n"
                    except Exception as e:
                        logger.error(f"Error handling menu: {e}", exc_info=True)
                        return "1\n"
                else:
                    # Couldn't extract options, auto-select 1
                    logger.warning("Couldn't extract menu options, auto-selecting 1")
                    return "1\n"
        
        # Unknown prompt type - log and deny
        logger.warning(f"Unknown prompt type, denying: {prompt_text[:100]}")
        return "n\n"
    
    def _parse_permission_request(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a line to detect permission requests from Claude Code.
        
        Args:
            line: Output line from Claude Code
            
        Returns:
            Dictionary with permission details if detected, None otherwise
        """
        # Detect interactive yes/no prompts (most common from Claude)
        # Patterns like: "Allow access to /path? (y/n)", "Do you want to proceed? (yes/no)"
        interactive_patterns = [
            r'\(y/n\)',
            r'\(yes/no\)',
            r'\[y/N\]',
            r'\[Y/n\]',
            r'\(y/N\)',
            r'\(Y/n\)',
        ]
        
        for pattern in interactive_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                # This is an interactive prompt
                return {
                    "action_type": "interactive_prompt",
                    "details": {
                        "description": line.strip(),
                        "prompt_type": "yes_no"
                    }
                }
        
        # Detect specific permission patterns
        permission_patterns = [
            (r'(?:Allow|Grant|Trust|Permit)\s+(?:access to|directory|path):\s*(.+)', "directory_access"),
            (r'(?:Edit|Modify|Create|Delete)\s+(?:file|directory):\s*(.+)', "file_edit"),
            (r'(?:Run|Execute)\s+command:\s*(.+)', "command_exec"),
            (r'(?:Install|Add)\s+(?:package|dependency):\s*(.+)', "package_install"),
        ]
        
        for pattern, action_type in permission_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return {
                    "action_type": action_type,
                    "details": {
                        "description": line,
                        "target": match.group(1).strip()
                    }
                }
        
        # Generic permission request detection (fallback)
        permission_keywords = ["approve", "confirm", "allow", "permit", "trust", "authorize"]
        if any(keyword in line.lower() for keyword in permission_keywords):
            # Check if it looks like a question
            if "?" in line or line.strip().endswith(":"):
                return {
                    "action_type": "generic",
                    "details": {
                        "description": line.strip()
                    }
                }
        
        return None
    
    async def _handle_permission_request(self, request: Dict[str, Any]) -> bool:
        """
        Handle a permission request by calling the callback.
        
        Args:
            request: Permission request details
            
        Returns:
            True if approved, False if denied
        """
        if not self.permission_callback:
            logger.warning("No permission callback set, auto-denying request")
            return False
        
        try:
            request_id = str(uuid.uuid4())
            logger.info(f"Processing permission request {request_id}: {request['action_type']}")
            
            # Call the permission callback
            approved = await self.permission_callback(
                request["action_type"],
                request["details"]
            )
            
            logger.info(f"Permission request {request_id} {'approved' if approved else 'denied'}")
            return approved
        
        except Exception as e:
            logger.error(f"Error handling permission request: {e}", exc_info=True)
            return False
    
    def set_permission_callback(self, callback: Callable) -> None:
        """
        Set the permission callback function.
        
        Args:
            callback: Async callback function for permission requests
        """
        self.permission_callback = callback
        logger.info("Permission callback updated")
