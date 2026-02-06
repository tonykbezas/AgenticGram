"""
Orchestrator for AgenticGram.
Manages command routing between Claude Code, OpenCode, and OpenRouter.
"""

import logging
import asyncio
import uuid
from typing import Dict, Any, Optional, Callable
from datetime import datetime

from src.claude.claude_client import ClaudeClient
from src.opencode_client import OpenCodeClient
from .openrouter_handler import OpenRouterHandler
from src.claude.session_manager import SessionManager, PermissionRequest


logger = logging.getLogger(__name__)


class Orchestrator:
    """Orchestrates command execution across different AI backends."""

    def __init__(
        self,
        session_manager: SessionManager,
        openrouter_api_key: Optional[str] = None,
        claude_code_path: Optional[str] = None,
        opencode_path: Optional[str] = None
    ):
        """
        Initialize orchestrator.

        Args:
            session_manager: SessionManager instance
            openrouter_api_key: Optional OpenRouter API key for fallback
            claude_code_path: Optional custom path to Claude CLI executable
            opencode_path: Optional custom path to OpenCode CLI executable
        """
        self.session_manager = session_manager
        self.claude_client = ClaudeClient(claude_path=claude_code_path)
        self.opencode_client = OpenCodeClient(opencode_path=opencode_path)
        self.openrouter_handler = OpenRouterHandler(openrouter_api_key) if openrouter_api_key else None
        self.permission_callback: Optional[Callable] = None

        # Track active executions per user for cancellation
        self._active_tasks: Dict[int, asyncio.Task] = {}

        # Set up permission callbacks for both CLIs
        self.claude_client.set_permission_callback(self._permission_callback_wrapper)
        self.opencode_client.set_permission_callback(self._permission_callback_wrapper)
    
    async def check_claude_availability(self) -> bool:
        """
        Check if Claude Code CLI is available.
        
        Returns:
            True if available, False otherwise
        """
        return await self.claude_client.check_availability()
    
    async def check_opencode_availability(self) -> bool:
        """
        Check if OpenCode CLI is available.
        
        Returns:
            True if available, False otherwise
        """
        return await self.opencode_client.check_availability()
    
    async def check_openrouter_availability(self) -> bool:
        """
        Check if OpenRouter API is available.
        
        Returns:
            True if available, False otherwise
        """
        if not self.openrouter_handler:
            return False
        return await self.openrouter_handler.check_availability()
    
    def set_permission_callback(self, callback: Callable) -> None:
        """
        Set the permission callback for user approvals.
        
        Args:
            callback: Async callback function
                     Signature: async def callback(action_type: str, details: dict, chat_id: int) -> bool
        """
        self.permission_callback = callback
    
    async def _permission_callback_wrapper(self, action_type: str, details: dict) -> bool:
        """
        Wrapper for permission callback that logs to database.
        
        Args:
            action_type: Type of action requiring permission
            details: Details about the action
            
        Returns:
            True if approved, False if denied
        """
        if not self.permission_callback:
            logger.warning("No permission callback set, denying request")
            return False
        
        try:
            approved = await self.permission_callback(action_type, details)
            return approved
        except Exception as e:
            logger.error(f"Error in permission callback: {e}", exc_info=True)
            return False
    
    async def execute_command(
        self,
        instruction: str,
        telegram_id: int,
        chat_id: int,
        output_callback: Optional[Callable] = None,
        force_openrouter: bool = False,
        continue_conversation: bool = True
    ) -> Dict[str, Any]:
        """
        Execute a command using available AI backend.
        
        Args:
            instruction: The instruction to execute
            telegram_id: Telegram user ID
            chat_id: Telegram chat ID for permission requests
            output_callback: Optional callback for streaming output updates
            force_openrouter: Force use of OpenRouter instead of CLI
            continue_conversation: Whether to continue previous conversation
            
        Returns:
            Dictionary with execution result
        """
        # Create a task for the execution logic
        task = asyncio.create_task(self._execute_command_internal(
            instruction, telegram_id, chat_id, output_callback, force_openrouter, continue_conversation
        ))
        
        # Track the task
        self._active_tasks[telegram_id] = task
        
        try:
            return await task
        except asyncio.CancelledError:
            logger.info(f"Command execution cancelled for user {telegram_id}")
            return {
                "success": False,
                "output": "[Execution cancelled by user]",
                "error": "Cancelled by user via /stop"
            }
        finally:
            # Remove from active tasks
            if telegram_id in self._active_tasks:
                del self._active_tasks[telegram_id]

    async def _execute_command_internal(
        self,
        instruction: str,
        telegram_id: int,
        chat_id: int,
        output_callback: Optional[Callable] = None,
        force_openrouter: bool = False,
        continue_conversation: bool = True
    ) -> Dict[str, Any]:
        """Internal execution logic (wrapped by execute_command for cancellation)."""
        # Get or create session
        session = self.session_manager.get_session(telegram_id)
        if not session:
            session = self.session_manager.create_session(telegram_id)
        
        # Update session usage
        session.last_used = datetime.now()
        session.message_count += 1
        self.session_manager.update_session(session)
        
        logger.info(f"Executing command for user {telegram_id}, session {session.session_id}, agent_type: {session.agent_type}")

        # Check availability of all backends
        claude_available = await self.check_claude_availability()
        opencode_available = await self.check_opencode_availability()
        openrouter_available = await self.check_openrouter_availability()

        # Determine which CLI to use based on availability and user selection
        actual_agent_type = session.agent_type
        selected_but_unavailable = False
        note = ""

        # If selected CLI is unavailable, switch to the available one
        if actual_agent_type == "opencode" and not opencode_available:
            if claude_available:
                actual_agent_type = "claude"
                selected_but_unavailable = True
                note = "ℹ️ OpenCode CLI unavailable, using Claude Code CLI"
                logger.warning(f"OpenCode unavailable, switching to Claude Code CLI")
            elif openrouter_available:
                actual_agent_type = "openrouter"
                selected_but_unavailable = True
                note = "ℹ️ OpenCode CLI unavailable, using OpenRouter"
                logger.warning(f"OpenCode unavailable, switching to OpenRouter")

        elif actual_agent_type == "claude" and not claude_available:
            if opencode_available:
                actual_agent_type = "opencode"
                selected_but_unavailable = True
                note = "ℹ️ Claude Code CLI unavailable, using OpenCode CLI"
                logger.warning(f"Claude unavailable, switching to OpenCode CLI")
            elif openrouter_available:
                actual_agent_type = "openrouter"
                selected_but_unavailable = True
                note = "ℹ️ Claude Code CLI unavailable, using OpenRouter"
                logger.warning(f"Claude unavailable, switching to OpenRouter")

        # Model selection
        from src.claude.session_manager import OPENCODE_DEFAULT_MODEL
        model = session.model
        
        # Use appropriate default model based on actual agent type
        if actual_agent_type == "opencode" and model in ["sonnet", "opus", "haiku"]:
            model = OPENCODE_DEFAULT_MODEL
        elif actual_agent_type == "claude" and model.startswith("glm"):
            model = "sonnet"

        # Env override for non-Claude models
        env_override = None
        if model.startswith("qwen/") or model.startswith("glm"):
            if self.openrouter_handler:
                env_override = {
                    "ANTHROPIC_BASE_URL": "https://openrouter.ai/api/v1",
                    "ANTHROPIC_API_KEY": self.openrouter_handler.api_key
                }

        # Execute using determined agent type
        if actual_agent_type == "claude":
            if session.bypass_mode:
                logger.info(f"Using Claude Code CLI with pipes, model: {model}")
                result = await self.claude_client.execute_with_pipes(
                    instruction=instruction,
                    work_dir=session.work_dir,
                    output_callback=output_callback,
                    model=model,
                    continue_conversation=continue_conversation,
                    env_override=env_override
                )
            else:
                logger.info(f"Using Claude Code CLI with PTY, model: {model}")
                result = await self.claude_client.execute_command(
                    instruction=instruction,
                    work_dir=session.work_dir,
                    output_callback=output_callback,
                    permission_context={"chat_id": chat_id},
                    model=model,
                    continue_conversation=continue_conversation,
                    env_override=env_override
                )
            
            return {
                **result,
                "backend": "claude_code" + ("_bypass" if session.bypass_mode else "_pty"),
                "session_id": session.session_id,
                "note": note
            }

        elif actual_agent_type == "opencode":
            logger.info(f"Using OpenCode CLI, model: {model}")
            result = await self.opencode_client.execute_command(
                instruction=instruction,
                work_dir=session.work_dir,
                output_callback=output_callback,
                permission_context={"chat_id": chat_id},
                model=model,
                continue_conversation=continue_conversation,
                env_override=env_override
            )
            
            return {
                **result,
                "backend": "opencode",
                "session_id": session.session_id,
                "note": note
            }

        elif actual_agent_type == "openrouter":
            if not openrouter_available:
                return {
                    "success": False,
                    "output": "",
                    "error": "No AI backend available",
                    "backend": "none"
                }
            
            logger.info(f"Using OpenRouter API, model: {model}")
            result = await self.openrouter_handler.execute_instruction(
                instruction=instruction,
                model=model,
                system_prompt="You are a helpful AI coding assistant. Provide clear, concise responses."
            )
            
            return {
                **result,
                "backend": "openrouter",
                "session_id": session.session_id,
                "note": note
            }
        
        return {
            "success": False,
            "output": "",
            "error": "No AI backend available",
            "backend": "none"
        }
    
    async def stop_execution(self, telegram_id: int) -> bool:
        """
        Stop any active execution for the given user.
        
        Args:
            telegram_id: Telegram user ID
            
        Returns:
            True if a task was stopped, False otherwise
        """
        if telegram_id in self._active_tasks:
            task = self._active_tasks[telegram_id]
            logger.info(f"Stopping active execution for user {telegram_id}")
            task.cancel()
            return True
        return False
    
    async def cleanup(self) -> None:
        """Clean up resources."""
        if self.openrouter_handler:
            await self.openrouter_handler.close()
        logger.info("Orchestrator cleanup completed")