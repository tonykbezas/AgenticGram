"""
Claude Code CLI Client for AgenticGram.
Manages interaction with Claude Code CLI, including permission handling.
"""

import asyncio
import logging
import re
import uuid
from typing import Optional, Callable, Dict, Any
from pathlib import Path

from .pty_wrapper import PTYWrapper

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Handles Claude Code CLI execution and permission management."""
    
    def __init__(self, permission_callback: Optional[Callable] = None, claude_path: Optional[str] = None):
        """
        Initialize Claude Code client.
        
        Args:
            permission_callback: Async callback function for permission requests
                                Signature: async def callback(action_type: str, details: dict) -> bool
            claude_path: Optional custom path to Claude CLI executable
        """
        self.permission_callback = permission_callback
        self.pending_permissions: Dict[str, asyncio.Future] = {}
        self.claude_path = claude_path or "claude"
        
        self.pty_wrapper = PTYWrapper()
        
        logger.info(f"Claude client initialized with path: {self.claude_path}")
    
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
            return False
        except Exception as e:
            logger.error(f"Error checking Claude CLI availability: {e}", exc_info=True)
            return False
    
    async def execute_command(
        self,
        instruction: str,
        work_dir: str,
        output_callback: Optional[Callable[[str], Any]] = None,
        timeout: int = 1800,
        permission_context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Execute a command via Claude Code CLI with PTY.
        
        Args:
            instruction: The instruction to send to Claude Code
            work_dir: Working directory for the command
            output_callback: Optional callback for streaming output
            timeout: Command timeout in seconds
            permission_context: Optional context to pass to permission callback (e.g. chat_id)
            
        Returns:
            Dictionary with 'success', 'output', and optional 'error' keys
        """
        try:
            Path(work_dir).mkdir(parents=True, exist_ok=True)
            
            command = [
                self.claude_path,
                instruction
            ]
            
            logger.info(f"Executing Claude CLI with PTY in {work_dir}")
            
            # Create a localized prompt handler that captures the context
            async def scoped_prompt_handler(text: str) -> str:
                return await self._handle_interactive_prompt(text, permission_context)
            
            result = await self.pty_wrapper.execute_with_pty(
                command=command,
                cwd=work_dir,
                prompt_callback=scoped_prompt_handler,
                output_callback=output_callback,
                timeout=timeout
            )
            logger.info(f"Tonyy: {result}")
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
    
    async def _handle_interactive_prompt(self, prompt_text: str, context: Dict[str, Any] = None) -> str:
        """
        Handle interactive prompts from Claude CLI.
        
        Args:
            prompt_text: The prompt text
            context: Context for permission callback
            
        Returns:
            Response to send to Claude
        """
        trust_patterns = [
            "Yes, I trust this folder",
            "Is this a project you created",
            "Quick safety check",
            "trust this folder"
        ]
        
        if any(pattern in prompt_text for pattern in trust_patterns):
            logger.info("Auto-approving directory trust prompt")
            return "1\n"
        
        if any(indicator in prompt_text for indicator in ["(y/n)", "(yes/no)", "[Y/n]", "[y/N]"]):
            if self.permission_callback:
                logger.info("Forwarding yes/no prompt to user via Telegram")
                try:
                    # Pass context if available
                    approved = await self.permission_callback("interactive_prompt", {
                        "description": prompt_text,
                        "prompt_type": "yes_no",
                        **(context or {})
                    })
                    response = "y\n" if approved else "n\n"
                    logger.info(f"User {'approved' if approved else 'denied'} prompt")
                    return response
                except Exception as e:
                    logger.error(f"Error in permission callback: {e}", exc_info=True)
                    return "n\n"
            else:
                logger.warning("No permission callback set, denying prompt")
                return "n\n"
        
        if re.search(r'^\s*\d+\.', prompt_text, re.MULTILINE):
            if self.permission_callback:
                logger.info("Detected menu prompt, extracting options...")
                
                menu_options = self.pty_wrapper._extract_menu_options(prompt_text)
                
                if menu_options:
                    logger.info(f"Found {len(menu_options)} menu options")
                    try:
                        response_number = await self.permission_callback("menu_prompt", {
                            "description": prompt_text,
                            "prompt_type": "menu",
                            "options": menu_options,
                            **(context or {})
                        })
                        
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
                    logger.warning("Couldn't extract menu options, auto-selecting 1")
                    return "1\n"
        
        logger.warning(f"Unknown prompt type, denying: {prompt_text[:100]}")
        return "n\n"
    
    def set_permission_callback(self, callback: Callable) -> None:
        """Set the permission callback function."""
        self.permission_callback = callback
        logger.info("Permission callback updated")
