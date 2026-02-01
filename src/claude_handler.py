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
        session_id: str,
        work_dir: str,
        output_callback: Optional[Callable[[str], Any]] = None,
        timeout: int = 1800  # 30 minutes for long tasks
    ) -> Dict[str, Any]:
        """
        Execute a command via Claude Code CLI with interactive permission handling.
        
        Args:
            instruction: The instruction to send to Claude Code
            session_id: Session ID for context persistence
            work_dir: Working directory for the session
            timeout: Command timeout in seconds
            
        Returns:
            Dictionary with 'success', 'output', and optional 'error' keys
        """
        try:
            # Ensure working directory exists
            Path(work_dir).mkdir(parents=True, exist_ok=True)
            
            # Start Claude Code process
            process = await asyncio.create_subprocess_exec(
                self.claude_path,
                "--session-id", session_id,
                instruction,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir
            )
            
            logger.info(f"Started Claude CLI process with session {session_id} in {work_dir}")
            
            # Handle interactive I/O with permission requests and streaming
            output_lines = []
            error_lines = []
            last_callback_time = 0
            CALLBACK_INTERVAL = 2.5  # Send update every 2.5 seconds
            
            try:
                # Read output with timeout
                async with asyncio.timeout(timeout):
                    # Create tasks for reading stdout and waiting for process
                    async def read_stdout():
                        """Read stdout line by line and handle permissions."""
                        nonlocal last_callback_time
                        if not process.stdout:
                            return
                        
                        while True:
                            line = await process.stdout.readline()
                            if not line:  # EOF reached
                                break
                            
                            decoded_line = line.decode().strip()
                            output_lines.append(decoded_line)
                            logger.debug(f"Claude output: {decoded_line}")
                            
                            # Check for permission requests
                            permission_request = self._parse_permission_request(decoded_line)
                            if permission_request:
                                approved = await self._handle_permission_request(permission_request)
                                
                                # Send response to Claude Code
                                if process.stdin:
                                    response = "y\n" if approved else "n\n"
                                    process.stdin.write(response.encode())
                                    await process.stdin.drain()
                                    logger.info(f"Sent permission response: {response.strip()}")
                            
                            # Call streaming callback periodically
                            import time
                            current_time = time.time()
                            if output_callback and (current_time - last_callback_time) >= CALLBACK_INTERVAL:
                                try:
                                    await output_callback("\n".join(output_lines))
                                    last_callback_time = current_time
                                except Exception as e:
                                    logger.error(f"Error in output callback: {e}")
                    
                    # Wait for both stdout reading and process completion
                    await asyncio.gather(
                        read_stdout(),
                        process.wait()
                    )
                
                # Final callback with complete output
                if output_callback and output_lines:
                    try:
                        await output_callback("\n".join(output_lines))
                    except Exception as e:
                        logger.error(f"Error in final callback: {e}")
                
            except asyncio.TimeoutError:
                logger.warning(f"Command timed out after {timeout} seconds")
                process.kill()
                await process.wait()
                return {
                    "success": False,
                    "output": "\n".join(output_lines),
                    "error": f"Command execution timed out after {timeout} seconds"
                }
            
            # Read any remaining stderr
            if process.stderr:
                stderr_data = await process.stderr.read()
                if stderr_data:
                    error_lines.append(stderr_data.decode().strip())
            
            output = "\n".join(output_lines)
            error = "\n".join(error_lines)
            
            if process.returncode == 0:
                logger.info(f"Command completed successfully for session {session_id}")
                return {
                    "success": True,
                    "output": output
                }
            else:
                logger.error(f"Command failed with return code {process.returncode}")
                return {
                    "success": False,
                    "output": output,
                    "error": error or f"Command failed with return code {process.returncode}"
                }
        
        except Exception as e:
            logger.error(f"Error executing Claude Code command: {e}", exc_info=True)
            return {
                "success": False,
                "output": "",
                "error": f"Unexpected error: {str(e)}"
            }
    
    def _parse_permission_request(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a line to detect permission requests from Claude Code.
        
        Args:
            line: Output line from Claude Code
            
        Returns:
            Dictionary with permission details if detected, None otherwise
        """
        # Common permission patterns from Claude Code
        patterns = [
            (r"(?:Edit|Modify|Create|Delete)\s+(?:file|directory):\s*(.+)", "file_edit"),
            (r"(?:Run|Execute)\s+command:\s*(.+)", "command_exec"),
            (r"(?:Install|Add)\s+(?:package|dependency):\s*(.+)", "package_install"),
        ]
        
        for pattern, action_type in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return {
                    "action_type": action_type,
                    "details": {
                        "description": line,
                        "target": match.group(1).strip()
                    }
                }
        
        # Generic permission request detection
        if any(keyword in line.lower() for keyword in ["approve", "confirm", "allow", "permit", "(y/n)"]):
            return {
                "action_type": "generic",
                "details": {
                    "description": line
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
