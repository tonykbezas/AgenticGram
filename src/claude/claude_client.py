"""
Claude Code CLI Client for AgenticGram.
Manages interaction with Claude Code CLI, including permission handling.
"""

import asyncio
import logging
import re
import json
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
        permission_context: Dict[str, Any] = None,
        model: str = "sonnet",
        continue_conversation: bool = True,
        env_override: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Execute a command via Claude Code CLI with PTY.

        Args:
            instruction: The instruction to send to Claude Code
            work_dir: Working directory for the command
            output_callback: Optional callback for streaming output
            timeout: Command timeout in seconds
            permission_context: Optional context to pass to permission callback (e.g. chat_id)
            model: Claude model to use (sonnet, opus, haiku, or full name)
            continue_conversation: Whether to continue previous conversation in this directory
            env_override: Optional environment variables to override (for OpenRouter models)

        Returns:
            Dictionary with 'success', 'output', and optional 'error' keys
        """
        try:
            Path(work_dir).mkdir(parents=True, exist_ok=True)

            command = [
                self.claude_path,
                "--model", model,
            ]

            # Add --continue to maintain conversation context
            if continue_conversation:
                command.append("--continue")

            command.append(instruction)
            
            logger.info(f"Executing Claude CLI with PTY in {work_dir}")
            
            # Create a localized prompt handler that captures the context
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

    async def execute_with_pipes(
        self,
        instruction: str,
        work_dir: str,
        output_callback: Optional[Callable[[str], Any]] = None,
        timeout: int = 1800,
        model: str = "sonnet",
        continue_conversation: bool = True,
        env_override: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Execute command via Claude Code CLI using pipes (bypass mode).

        Uses -p (print mode) with --permission-mode bypassPermissions for clean output
        without TUI artifacts. No interactive prompts - all permissions auto-approved.

        Args:
            instruction: The instruction to send to Claude Code
            work_dir: Working directory for the command
            output_callback: Optional callback for streaming output
            timeout: Command timeout in seconds
            model: Claude model to use (sonnet, opus, haiku, or full name)
            continue_conversation: Whether to continue previous conversation in this directory
            env_override: Optional environment variables to override (for OpenRouter models)

        Returns:
            Dictionary with 'success', 'output', and optional 'error' keys
        """
        try:
            Path(work_dir).mkdir(parents=True, exist_ok=True)

            command = [
                self.claude_path,
                "-p",  # Print mode (non-interactive)
                "--model", model,
                "--permission-mode", "bypassPermissions",  # Skip all permission prompts
                "--output-format", "stream-json",  # Structured streaming output
                "--verbose",  # Required for stream-json
            ]

            # Add --continue to maintain conversation context
            if continue_conversation:
                command.append("--continue")

            command.append(instruction)

            logger.info(f"Executing Claude CLI with pipes (bypass mode) in {work_dir}")

            # Prepare environment variables
            import os
            env = os.environ.copy()
            if env_override:
                env.update(env_override)
                logger.info(f"Using environment override for model: {model}")

            # Create subprocess with larger buffer limit (16MB instead of default 64KB)
            # This prevents LimitOverrunError for large Claude outputs
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=env,
                limit=16 * 1024 * 1024  # 16MB buffer limit
            )

            output_lines = []
            final_output = ""

            # Read streaming JSON output
            async def read_stream():
                nonlocal final_output
                while True:
                    try:
                        line = await process.stdout.readline()
                    except asyncio.LimitOverrunError as e:
                        # Handle extremely large lines that exceed buffer limit
                        logger.warning(f"Line exceeded buffer limit: {e}")
                        # Read remaining data in chunks to clear the buffer
                        try:
                            chunk = await process.stdout.read(1024 * 1024)  # Read 1MB
                            if chunk:
                                output_lines.append("[Output truncated - line too large]")
                                final_output = "\n".join(output_lines)
                        except Exception:
                            pass
                        continue

                    if not line:
                        break

                    try:
                        line_text = line.decode('utf-8', errors='replace').strip()
                        if not line_text:
                            continue

                        # Parse JSON line
                        data = json.loads(line_text)

                        # Extract content based on message type
                        content = self._extract_content_from_stream(data)
                        if content:
                            output_lines.append(content)
                            final_output = "\n".join(output_lines)

                            if output_callback:
                                try:
                                    await output_callback(final_output)
                                except Exception as e:
                                    logger.error(f"Error in output callback: {e}")

                    except json.JSONDecodeError:
                        # Not JSON, append as raw text
                        raw_text = line.decode('utf-8', errors='replace').strip()
                        if raw_text:
                            output_lines.append(raw_text)
                            final_output = "\n".join(output_lines)

            try:
                await asyncio.wait_for(read_stream(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                return {
                    "success": False,
                    "output": final_output,
                    "error": f"Timed out after {timeout} seconds"
                }

            await process.wait()

            # Read any stderr
            stderr_data = await process.stderr.read()
            stderr_text = stderr_data.decode('utf-8', errors='replace').strip()
            if stderr_text:
                logger.warning(f"Claude CLI stderr: {stderr_text}")

            success = process.returncode == 0

            if success:
                logger.info("Pipes command completed successfully")
            else:
                logger.error(f"Pipes command failed with code {process.returncode}")

            return {
                "success": success,
                "output": final_output,
                "returncode": process.returncode,
                "stderr": stderr_text if stderr_text else None
            }

        except Exception as e:
            logger.error(f"Error executing Claude Code with pipes: {e}", exc_info=True)
            return {
                "success": False,
                "output": "",
                "error": f"Unexpected error: {str(e)}"
            }

    def _extract_content_from_stream(self, data: dict) -> Optional[str]:
        """
        Extract readable content from stream-json message.

        Args:
            data: Parsed JSON data from stream

        Returns:
            Extracted content string or None
        """
        msg_type = data.get("type", "")

        # Handle different message types from Claude stream-json
        if msg_type == "assistant":
            # Assistant message with content
            message = data.get("message", {})
            content_blocks = message.get("content", [])
            texts = []
            for block in content_blocks:
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
            return "\n".join(texts) if texts else None

        elif msg_type == "content_block_delta":
            # Streaming delta
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                return delta.get("text", "")

        elif msg_type == "result":
            # Final result message
            result = data.get("result", "")
            if result:
                return result
            # Check for subresult
            subresult = data.get("subresult", "")
            if subresult:
                return subresult

        elif msg_type == "system":
            # System message (usually ignorable)
            return None

        return None
