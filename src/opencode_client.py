"""
OpenCode CLI Client for AgenticGram.
Manages interaction with OpenCode CLI.
"""

import asyncio
import logging
import re
import json
import uuid
from typing import Optional, Callable, Dict, Any
from pathlib import Path

from src.claude.pty_wrapper import PTYWrapper

logger = logging.getLogger(__name__)


class OpenCodeClient:
    """Handles OpenCode CLI execution and permission management."""
    
    def __init__(self, permission_callback: Optional[Callable] = None, opencode_path: Optional[str] = None):
        """
        Initialize OpenCode client.
        
        Args:
            permission_callback: Async callback function for permission requests
                                Signature: async def callback(action_type: str, details: dict) -> bool
            opencode_path: Optional custom path to OpenCode CLI executable
        """
        self.permission_callback = permission_callback
        self.pending_permissions: Dict[str, asyncio.Future] = {}
        self.opencode_path = opencode_path or "opencode"
        
        self.pty_wrapper = PTYWrapper()
        
        logger.info(f"OpenCode client initialized with path: {self.opencode_path}")
    
    async def check_availability(self) -> bool:
        """
        Check if OpenCode CLI is available.
        
        Returns:
            True if available, False otherwise
        """
        try:
            logger.debug(f"Checking OpenCode CLI availability at: {self.opencode_path}")
            
            process = await asyncio.create_subprocess_exec(
                self.opencode_path, "--help",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info("OpenCode CLI is available")
                return True
            else:
                logger.warning(f"OpenCode CLI check failed: {stderr.decode().strip()}")
                return False
        except FileNotFoundError:
            logger.error(f"OpenCode CLI not found at '{self.opencode_path}'")
            return False
        except Exception as e:
            logger.error(f"Error checking OpenCode CLI availability: {e}", exc_info=True)
            return False
    
    async def execute_command(
        self,
        instruction: str,
        work_dir: str,
        output_callback: Optional[Callable[[str], Any]] = None,
        timeout: int = 1800,
        permission_context: Dict[str, Any] = None,
        model: str = "default",
        continue_conversation: bool = True,
        env_override: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Execute a command via OpenCode CLI with PTY.

        Args:
            instruction: The instruction to send to OpenCode
            work_dir: Working directory for the command
            output_callback: Optional callback for streaming output
            timeout: Command timeout in seconds
            permission_context: Optional context to pass to permission callback (e.g. chat_id)
            model: Model to use
            continue_conversation: Whether to continue previous conversation in this directory
            env_override: Optional environment variables to override

        Returns:
            Dictionary with 'success', 'output', and optional 'error' keys
        """
        try:
            Path(work_dir).mkdir(parents=True, exist_ok=True)

            command = [
                self.opencode_path,
                "--cwd", work_dir,
            ]

            if model != "default":
                command.extend(["--model", model])

            if continue_conversation:
                command.append("--continue")

            command.append(instruction)
            
            logger.info(f"Executing OpenCode CLI with PTY in {work_dir}")
            
            async def scoped_prompt_handler(text: str) -> str:
                return await self._handle_interactive_prompt(text, permission_context)
            
            result = await self.pty_wrapper.execute_with_pty(
                command=command,
                cwd=work_dir,
                prompt_callback=scoped_prompt_handler,
                output_callback=output_callback,
                timeout=timeout,
                env_override=env_override
            )
            
            if result["success"]:
                logger.info(f"Command completed successfully")
            else:
                logger.error(f"Command failed: {result.get('error', 'Unknown error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing OpenCode command: {e}", exc_info=True)
            return {
                "success": False,
                "output": "",
                "error": f"Unexpected error: {str(e)}"
            }

    async def _handle_interactive_prompt(self, prompt_text: str, context: Dict[str, Any] = None) -> str:
        """
        Handle interactive prompts from OpenCode CLI.
        
        Args:
            prompt_text: The prompt text
            context: Context for permission callback
            
        Returns:
            Response to send to OpenCode
        """
        trust_patterns = [
            "trust this directory",
            "folder trust",
            "project you created",
            "safety check"
        ]
        
        if any(pattern in prompt_text.lower() for pattern in trust_patterns):
            logger.info("Auto-approving directory trust prompt")
            return "1\n"
        
        if any(indicator in prompt_text for indicator in ["(y/n)", "(yes/no)", "[Y/n]", "[y/N]"]):
            if self.permission_callback:
                logger.info("Forwarding yes/no prompt to user via Telegram")
                try:
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