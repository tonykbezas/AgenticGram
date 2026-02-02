"""
PTY Handler for AgenticGram
Manages pseudo-terminal execution for capturing interactive CLI programs.
"""

import os
import pty
import select
import subprocess
import asyncio
import re
import time
import logging
from typing import Callable, Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class PTYHandler:
    """Handles PTY-based subprocess execution with ANSI parsing and interactive prompts."""
    
    def __init__(self):
        """Initialize PTY handler."""
        # Regex to match ANSI escape codes
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        
        # Prompt detection patterns
        self.prompt_indicators = [
            "❯",  # Arrow indicator (common in TUI menus)
            "Enter to confirm",
            "Esc to cancel",
            "(y/n)",
            "(yes/no)",
            "[Y/n]",
            "[y/N]",
        ]
    
    def strip_ansi(self, text: str) -> str:
        """
        Remove ANSI escape codes from text.
        
        Args:
            text: Text potentially containing ANSI codes
            
        Returns:
            Clean text without ANSI codes
        """
        return self.ansi_escape.sub('', text)
    
    def _is_prompt(self, text: str, idle_time: float) -> bool:
        """
        Detect if text contains an interactive prompt.
        
        Args:
            text: Text to check
            idle_time: Seconds since last output
            
        Returns:
            True if text appears to be a prompt waiting for input
        """
        if not text:
            return False
        
        # Must have been idle for at least 1 second to avoid false positives
        if idle_time < 1.0:
            return False
        
        # Check for prompt indicators
        for indicator in self.prompt_indicators:
            if indicator in text:
                return True
        
        # Check for numbered menu options (1., 2., etc.)
        lines = text.strip().split('\n')
        if len(lines) >= 2:
            # Look for pattern like "1. Option" and "2. Option"
            has_numbered_options = any(
                re.match(r'^\s*\d+\.\s+', line) for line in lines[-3:]
            )
            if has_numbered_options:
                return True
        
        return False
    
    async def execute_with_pty(
        self,
        command: List[str],
        cwd: str,
        prompt_callback: Optional[Callable[[str], Any]] = None,
        output_callback: Optional[Callable[[str], Any]] = None,
        timeout: int = 1800
    ) -> Dict[str, Any]:
        """
        Execute command in a PTY and handle interactive prompts.
        
        Args:
            command: Command and arguments to execute
            cwd: Working directory
            prompt_callback: Async callback for handling prompts, receives clean prompt text
            output_callback: Async callback for streaming output
            timeout: Command timeout in seconds
            
        Returns:
            Dictionary with 'success', 'output', and optional 'error' keys
        """
        master_fd = None
        process = None
        
        try:
            # Create PTY
            master_fd, slave_fd = pty.openpty()
            logger.info(f"Created PTY for command: {' '.join(command)}")
            
            # Start process with PTY
            process = subprocess.Popen(
                command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                close_fds=True,
                preexec_fn=os.setsid  # Create new session
            )
            
            # Parent doesn't need slave fd
            os.close(slave_fd)
            
            logger.info(f"Started process PID {process.pid} in PTY")
            
            # Read loop
            output_buffer = ""
            clean_output = ""
            last_output_time = time.time()
            last_callback_time = 0
            CALLBACK_INTERVAL = 0.5  # Stream updates every 0.5 seconds
            
            start_time = time.time()
            
            while True:
                # Check timeout
                if time.time() - start_time > timeout:
                    logger.warning(f"Command timed out after {timeout} seconds")
                    process.kill()
                    return {
                        "success": False,
                        "output": clean_output,
                        "error": f"Timed out after {timeout} seconds"
                    }
                
                # Check if process finished
                if process.poll() is not None:
                    logger.info(f"Process finished with return code {process.returncode}")
                    break
                
                # Non-blocking read with timeout
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                
                if ready:
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            logger.debug("EOF reached on PTY")
                            break
                        
                        # Decode data
                        text = data.decode('utf-8', errors='replace')
                        output_buffer += text
                        
                        # Strip ANSI codes for clean text
                        clean_text = self.strip_ansi(output_buffer)
                        clean_output = clean_text
                        
                        last_output_time = time.time()
                        
                        # Log output
                        logger.debug(f"PTY output: {clean_text[:100]}")
                        
                    except OSError as e:
                        logger.error(f"Error reading from PTY: {e}")
                        break
                
                # Check for prompts (only if we have a callback)
                if prompt_callback:
                    idle_time = time.time() - last_output_time
                    
                    if self._is_prompt(clean_output, idle_time):
                        logger.info(f"Detected interactive prompt: {clean_output[-200:]}")
                        
                        # Call prompt callback
                        try:
                            response = await prompt_callback(clean_output)
                            
                            if response:
                                logger.info(f"Sending response to prompt: {response.strip()}")
                                os.write(master_fd, response.encode())
                                
                                # Clear buffer after responding
                                output_buffer = ""
                                clean_output = ""
                                last_output_time = time.time()
                        except Exception as e:
                            logger.error(f"Error in prompt callback: {e}", exc_info=True)
                
                # Stream output callback
                if output_callback and clean_output:
                    current_time = time.time()
                    if current_time - last_callback_time >= CALLBACK_INTERVAL:
                        try:
                            await output_callback(clean_output)
                            last_callback_time = current_time
                        except Exception as e:
                            logger.error(f"Error in output callback: {e}")
                
                # Small sleep to avoid busy waiting
                await asyncio.sleep(0.05)
            
            # Read any remaining output
            try:
                while True:
                    ready, _, _ = select.select([master_fd], [], [], 0.1)
                    if not ready:
                        break
                    data = os.read(master_fd, 4096)
                    if not data:
                        break
                    text = data.decode('utf-8', errors='replace')
                    output_buffer += text
                    clean_output = self.strip_ansi(output_buffer)
            except:
                pass
            
            # Final output callback
            if output_callback and clean_output:
                try:
                    await output_callback(clean_output)
                except:
                    pass
            
            # Check return code
            returncode = process.wait(timeout=5)
            success = (returncode == 0)
            
            return {
                "success": success,
                "output": clean_output,
                "returncode": returncode
            }
            
        except Exception as e:
            logger.error(f"Error in PTY execution: {e}", exc_info=True)
            return {
                "success": False,
                "output": clean_output if 'clean_output' in locals() else "",
                "error": str(e)
            }
            
        finally:
            # Cleanup
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except:
                    pass
            
            if process and process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except:
                    pass
