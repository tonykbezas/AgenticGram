"""
Orchestrator for AgenticGram.
Manages command routing between Claude Code and OpenRouter.
"""

import logging
import asyncio
import uuid
from typing import Dict, Any, Optional, Callable
from datetime import datetime

from src.claude.claude_client import ClaudeClient
from .openrouter_handler import OpenRouterHandler
from src.claude.session_manager import SessionManager, PermissionRequest


logger = logging.getLogger(__name__)


class Orchestrator:
    """Orchestrates command execution across different AI backends."""

    def __init__(
        self,
        session_manager: SessionManager,
        openrouter_api_key: Optional[str] = None,
        claude_code_path: Optional[str] = None
    ):
        """
        Initialize orchestrator.

        Args:
            session_manager: SessionManager instance
            openrouter_api_key: Optional OpenRouter API key for fallback
            claude_code_path: Optional custom path to Claude CLI executable
        """
        self.session_manager = session_manager
        self.claude_client = ClaudeClient(claude_path=claude_code_path)
        self.openrouter_handler = OpenRouterHandler(openrouter_api_key) if openrouter_api_key else None
        self.permission_callback: Optional[Callable] = None

        # Track active executions per user for cancellation
        self._active_tasks: Dict[int, asyncio.Task] = {}

        # Set up Claude handler permission callback
        self.claude_client.set_permission_callback(self._permission_callback_wrapper)
    
    async def check_claude_availability(self) -> bool:
        """
        Check if Claude Code CLI is available.
        
        Returns:
            True if available, False otherwise
        """
        return await self.claude_client.check_availability()
    
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
        
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Get current session (this is a simplified version - in practice, 
        # we'd need to track which session is currently active)
        # For now, we'll just call the callback without logging
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
            force_openrouter: Force use of OpenRouter instead of Claude
            
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
        
        logger.info(f"Executing command for user {telegram_id}, session {session.session_id}")
        
        # Try Claude Code first (unless forced to use OpenRouter)
        if not force_openrouter:
            claude_available = await self.check_claude_availability()

            if claude_available:
                # Check if bypass mode is enabled
                if session.bypass_mode:
                    logger.info(f"Using Claude Code CLI with pipes (bypass mode), model: {session.model}, continue: {continue_conversation}")
                    result = await self.claude_client.execute_with_pipes(
                        instruction=instruction,
                        work_dir=session.work_dir,
                        output_callback=output_callback,
                        model=session.model,
                        continue_conversation=continue_conversation
                    )
                else:
                    logger.info(f"Using Claude Code CLI with PTY (interactive mode), model: {session.model}, continue: {continue_conversation}")
                    result = await self.claude_client.execute_command(
                        instruction=instruction,
                        work_dir=session.work_dir,
                        output_callback=output_callback,
                        permission_context={"chat_id": chat_id},
                        model=session.model,
                        continue_conversation=continue_conversation
                    )

                # Check if we should fallback to OpenRouter
                if result["success"]:
                    return {
                        **result,
                        "backend": "claude_code" + ("_bypass" if session.bypass_mode else "_pty"),
                        "session_id": session.session_id
                    }
                else:
                    # Check if error is quota-related
                    error = result.get("error", "")
                    if any(keyword in error.lower() for keyword in ["quota", "rate limit", "usage limit"]):
                        logger.warning("Claude Code quota exceeded, falling back to OpenRouter")
                        force_openrouter = True
                    else:
                        # Return Claude error
                        return {
                            **result,
                            "backend": "claude_code" + ("_bypass" if session.bypass_mode else "_pty"),
                            "session_id": session.session_id
                        }
        
        # Fallback to OpenRouter
        if force_openrouter or not await self.check_claude_availability():
            if not self.openrouter_handler:
                return {
                    "success": False,
                    "output": "",
                    "error": "Claude Code unavailable and OpenRouter not configured",
                    "backend": "none"
                }
            
            openrouter_available = await self.check_openrouter_availability()
            if not openrouter_available:
                return {
                    "success": False,
                    "output": "",
                    "error": "Both Claude Code and OpenRouter are unavailable",
                    "backend": "none"
                }
            
            logger.info("Using OpenRouter API")
            result = await self.openrouter_handler.execute_instruction(
                instruction=instruction,
                system_prompt="You are a helpful AI coding assistant. Provide clear, concise responses."
            )
            
            return {
                **result,
                "backend": "openrouter",
                "session_id": session.session_id
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
