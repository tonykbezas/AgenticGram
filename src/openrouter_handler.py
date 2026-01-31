"""
OpenRouter API Handler for AgenticGram.
Provides fallback AI capabilities when Claude Code is unavailable.
"""

import aiohttp
import logging
from typing import Optional, Dict, Any, List


logger = logging.getLogger(__name__)


class OpenRouterHandler:
    """Handles OpenRouter API integration as a fallback."""
    
    # Model priority list (try in order)
    DEFAULT_MODELS = [
        "anthropic/claude-3.5-sonnet",
        "qwen/qwen-2.5-coder-32b-instruct",
        "deepseek/deepseek-coder",
        "meta-llama/llama-3.1-70b-instruct"
    ]
    
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        """
        Initialize OpenRouter handler.
        
        Args:
            api_key: OpenRouter API key
            base_url: OpenRouter API base URL
        """
        self.api_key = api_key
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session exists."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self) -> None:
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def check_availability(self) -> bool:
        """
        Check if OpenRouter API is available.
        
        Returns:
            True if available, False otherwise
        """
        if not self.api_key:
            logger.warning("OpenRouter API key not configured")
            return False
        
        try:
            session = await self._ensure_session()
            async with session.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"}
            ) as response:
                if response.status == 200:
                    logger.info("OpenRouter API is available")
                    return True
                else:
                    logger.warning(f"OpenRouter API check failed: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Error checking OpenRouter availability: {e}")
            return False
    
    async def execute_instruction(
        self,
        instruction: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute an instruction via OpenRouter API.
        
        Args:
            instruction: The instruction/prompt to send
            model: Model to use (default: try models in priority order)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            system_prompt: Optional system prompt
            
        Returns:
            Dictionary with 'success', 'output', and optional 'error' keys
        """
        if not self.api_key:
            return {
                "success": False,
                "output": "",
                "error": "OpenRouter API key not configured"
            }
        
        models_to_try = [model] if model else self.DEFAULT_MODELS
        
        for current_model in models_to_try:
            try:
                logger.info(f"Trying OpenRouter model: {current_model}")
                result = await self._call_api(
                    instruction=instruction,
                    model=current_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system_prompt=system_prompt
                )
                
                if result["success"]:
                    return result
                else:
                    logger.warning(f"Model {current_model} failed: {result.get('error')}")
                    continue
            
            except Exception as e:
                logger.error(f"Error with model {current_model}: {e}")
                continue
        
        return {
            "success": False,
            "output": "",
            "error": "All OpenRouter models failed"
        }
    
    async def _call_api(
        self,
        instruction: str,
        model: str,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str]
    ) -> Dict[str, Any]:
        """
        Make API call to OpenRouter.
        
        Args:
            instruction: User instruction
            model: Model identifier
            max_tokens: Maximum tokens
            temperature: Sampling temperature
            system_prompt: Optional system prompt
            
        Returns:
            Dictionary with result
        """
        session = await self._ensure_session()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": instruction})
        
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/AgenticGram/universal-ai-cli-bot",
            "X-Title": "AgenticGram Bot"
        }
        
        try:
            async with session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    output = data["choices"][0]["message"]["content"]
                    
                    # Log usage for cost tracking
                    usage = data.get("usage", {})
                    logger.info(f"OpenRouter usage - Model: {model}, "
                              f"Tokens: {usage.get('total_tokens', 'unknown')}")
                    
                    return {
                        "success": True,
                        "output": output,
                        "model": model,
                        "usage": usage
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"OpenRouter API error {response.status}: {error_text}")
                    return {
                        "success": False,
                        "output": "",
                        "error": f"API error {response.status}: {error_text}"
                    }
        
        except asyncio.TimeoutError:
            logger.error("OpenRouter API request timed out")
            return {
                "success": False,
                "output": "",
                "error": "Request timed out"
            }
        except Exception as e:
            logger.error(f"OpenRouter API call failed: {e}", exc_info=True)
            return {
                "success": False,
                "output": "",
                "error": str(e)
            }
    
    async def stream_instruction(
        self,
        instruction: str,
        model: Optional[str] = None,
        callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Execute instruction with streaming response.
        
        Args:
            instruction: The instruction to send
            model: Model to use
            callback: Optional callback for streaming chunks
            
        Returns:
            Dictionary with complete result
        """
        # Streaming implementation for future enhancement
        # For now, fall back to regular execution
        return await self.execute_instruction(instruction, model)
