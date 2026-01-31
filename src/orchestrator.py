"""
Orchestrator for AgenticGram.
Manages command routing between Claude Code and OpenRouter.
"""

import logging
import uuid
from typing import Dict, Any, Optional, Callable
from datetime import datetime

from .claude_handler import ClaudeHandler
from .openrouter_handler import OpenRouterHandler
from .session_manager import SessionManager, PermissionRequest


logger = logging.getLogger(__name__)


class Orchestrator:
    """Orchestrates command execution across different AI backends."""
    
    def __init__(
        self,
        session_manager: SessionManager,
        openrouter_api_key: Optional[str] = None
    ):
        """
        Initialize orchestrator.
        
        Args:
            session_manager: SessionManager instance
            openrouter_api_key: Optional OpenRouter API key for fallback
        """
        self.session_manager = session_manager
        self.claude_handler = ClaudeHandler()
        self.openrouter_handler = OpenRouterHandler(openrouter_api_key) if openrouter_api_key else None
        self.permission_callback: Optional[Callable] = None
        
        # Set up Claude handler permission callback
        self.claude_handler.set_permission_callback(self._permission_callback_wrapper)
    
    async def check_claude_availability(self) -> bool:
        """
        Check if Claude Code CLI is available.
        
        Returns:
            True if available, False otherwise
        """
        return await self.claude_handler.check_availability()
    
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
        force_openrouter: bool = False
    ) -> Dict[str, Any]:
        """
        Execute a command using available AI backend.
        
        Args:
            instruction: The instruction to execute
            telegram_id: Telegram user ID
            chat_id: Telegram chat ID for permission requests
            force_openrouter: Force use of OpenRouter instead of Claude
            
        Returns:
            Dictionary with execution result
        """
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
                logger.info("Using Claude Code CLI")
                result = await self.claude_handler.execute_command(
                    instruction=instruction,
                    session_id=session.session_id,
                    work_dir=session.work_dir
                )
                
                # Check if we should fallback to OpenRouter
                if result["success"]:
                    return {
                        **result,
                        "backend": "claude_code",
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
                            "backend": "claude_code",
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
    
    async def cleanup(self) -> None:
        """Clean up resources."""
        if self.openrouter_handler:
            await self.openrouter_handler.close()
        logger.info("Orchestrator cleanup completed")
