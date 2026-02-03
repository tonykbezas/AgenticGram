"""
PTY Wrapper for AgenticGram
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


class PTYWrapper:
    """Handles PTY-based subprocess execution with ANSI parsing and interactive prompts."""
    
    def __init__(self):
        """Initialize PTY handler."""
        # Regex to match ANSI escape codes including OSC sequences
        self.ansi_escape = re.compile(
            r'(?:\x1B\]|\x9D).*?(?:\x1B\\|\x07)'  # OSC
            r'|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~]'  # CSI
            r'|(?:\x1B[PX^_].*?\x1B\\)'           # DCS/PM/APC
            r'|(?:\x1B[@-Z\\^_]|[\x80-\x9A\x9C-\x9F])', # Generic (excluding [ and ])
            re.VERBOSE | re.DOTALL
        )
        
        # Prompt detection patterns
        self.prompt_indicators = [
            "❯",  # Arrow indicator (common in TUI menus)
            "Enter to confirm",
            "Esc to cancel",
            "Tab to amend",
            "(y/n)",
            "(yes/no)",
            "[Y/n]",
            "[y/N]",
        ]
        
        # Animation patterns (loading spinners, progress indicators)
        self.animation_patterns = [
            r'[✻✶*✢·●✽⠂⠐⠁⠈⠄⠠⠀]+',  # Spinning stars/dots
            r'reading \d+ files?…',  # Progress messages
            r'\(ctrl\+o to expand\)',  # UI hints
            r'ought for\d+s\)',  # Timing info
        ]
        
        # Cache for message deduplication/TTL
        self._message_cache = {}
    
    def strip_ansi(self, text: str) -> str:
        """
        Remove ANSI escape codes and TUI artifacts from text.
        
        Args:
            text: Text potentially containing ANSI codes
            
        Returns:
            Clean text without ANSI codes or TUI artifacts
        """
        # First strip ANSI codes
        text = self.ansi_escape.sub('', text)
        
        # Then clean TUI artifacts
        return self._clean_tui_artifacts(text)
    
    def _clean_tui_artifacts(self, text: str) -> str:
        """
        Remove TUI artifacts like borders, headers, etc.
        
        Args:
            text: Text to clean
            
        Returns:
            Cleaned text
        """
        if not text:
            return ""
            
        # 1. Remove Claude Code header box (╭─── Claude Code ... ╰───...╯)
        text = re.sub(r'╭─── Claude Code.*?╰[─\s]*╯\s*', '', text, flags=re.DOTALL)
        
        # 2. Remove decorative lines (from user suggestion)
        # Matches sequences of 2 or more decorative characters
        text = re.sub(r'─{2,}|━{2,}|═{2,}|={2,}|-{2,}', '', text)
        
        # 3. Remove "noise" characters (spinners, blocks, etc.)
        # Note: We keep some structure chars but remove the specific noise ones for now
        # Removed ● (bullet) from here so it isn't stripped from message content
        # Added from user suggestion: ✶, ✻, ✽, ✢, ▐, ▛, ▜, ▌, ▝, ❯
        text = re.sub(r'[✶✻✽✢·▐▛▜▌▝❯✢]', '', text)
        
        # 4. Remove standalone TUI lines that are just borders (failsafe)
        text = re.sub(r'^\s*│\s*$', '', text, flags=re.MULTILINE)
        
        # 5. Remove "blob data" markers from logs if they leaked into output
        text = re.sub(r'\[\d+B blob data\]', '', text)
        
        # 6. Clean up excessive newlines
        # We reduce 3+ newlines (possibly with spaces) to 2
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        
        # 7. Remove non-printable characters (fixes "2B blob data" in logs)
        # Keeps newlines (\n), carriage returns (\r), and tabs (\t)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        
        # 8. Handle carriage returns to fix "duplicate" lines from animations
        text = self._process_carriage_returns(text)

        logger.info(f"Cleaned text: {text[:100]!r}...")
        return text

    def _process_carriage_returns(self, text: str) -> str:
        """
        Simulate terminal carriage return (\r) behavior to avoid duplicate lines.
        When a \r is found, it usually means the line is being rewritten.
        We keep the last 'frame' of the line.
        """
        if '\r' not in text:
            return text
            
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            if '\r' in line:
                # If the line has carriage returns, we essentially want the last
                # segment that doesn't start with \r, or we simulate the overwrite.
                # Simplest robust approach for logs/chat: take the content after the last \r
                parts = line.split('\r')
                # Filter empty parts avoiding artifacts if line ends with \r
                valid_parts = [p for p in parts if p]
                if valid_parts:
                    cleaned_lines.append(valid_parts[-1])
                else:
                    cleaned_lines.append("")
            else:
                cleaned_lines.append(line)
                
        return '\n'.join(cleaned_lines)
    
    def _is_animation_frame(self, text: str) -> bool:
        """
        Detect if text is just an animation frame.
        
        Args:
            text: Text to check
            
        Returns:
            True if text appears to be an animation frame
        """
        if not text:
            return True
            
        # If text contains significant alphanumeric content, it's likely NOT an animation
        # (unless it's a specific loading message pattern)
        has_content = bool(re.search(r'[a-zA-Z0-9]{2,}', text))
        
        # Check for specific loading message patterns first
        for pattern in self.animation_patterns:
            # If pattern is complex (contains alphabetic chars like 'reading'), check directly
            if re.search(r'[a-zA-Z]', pattern):
                if re.search(pattern, text):
                    return True
            # For symbol-only patterns, only match if we DON'T have other content
            elif re.search(pattern, text) and not has_content:
                return True
        
        # Check if mostly special characters (fallback)
        clean = re.sub(r'[\s\n\r]', '', text)
        if len(clean) > 0 and not has_content:
            special_chars = len(re.findall(r'[✻✶*✢·●✽⠂⠐⠁⠈⠄⠠]', clean))
            if special_chars / len(clean) > 0.5:
                return True
        
        return False
    
    def _extract_menu_options(self, text: str) -> Optional[list]:
        """
        Extract menu options from prompt text.
        
        Args:
            text: Prompt text containing menu
            
        Returns:
            List of option dicts with 'number' and 'text', or None
        """
        lines = text.strip().split('\n')
        options = []
        
        for line in lines:
            match = re.match(r'^\s*[❯\s]*\s*(\d+)\.\s+(.+?)\s*$', line)
            if match:
                number = match.group(1)
                text = match.group(2).strip()
                options.append({
                    'number': number,
                    'text': text
                })
        
        return options if options else None
    
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
        
        if idle_time < 1.0:
            return False
        
        for indicator in self.prompt_indicators:
            if indicator in text:
                return True
        
        lines = text.strip().split('\n')
        if len(lines) >= 2:
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
                preexec_fn=os.setsid
            )
            
            # Parent doesn't need slave fd
            os.close(slave_fd)
            
            logger.info(f"Started process PID {process.pid} in PTY")
            
            # Read loop
            output_buffer = ""
            clean_output = ""
            last_sent_output = ""  # Cache to prevent duplicate updates
            last_output_time = time.time()
            last_callback_time = 0
            CALLBACK_INTERVAL = 0.5
            
            start_time = time.time()
            
            while True:
                if time.time() - start_time > timeout:
                    logger.warning(f"Command timed out after {timeout} seconds")
                    process.kill()
                    return {
                        "success": False,
                        "output": clean_output,
                        "error": f"Timed out after {timeout} seconds"
                    }
                
                if process.poll() is not None:
                    logger.info(f"Process finished with return code {process.returncode}")
                    break
                
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                
                if ready:
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            logger.debug("EOF reached on PTY")
                            break
                        
                        text = data.decode('utf-8', errors='replace')
                        
                        # CAPTURE: Write raw output to file for debugging
                        try:
                            with open("terminal_output.log", "a", encoding="utf-8") as f:
                                # Write with timestamp marker for readability
                                f.write(text)
                        except Exception:
                            pass

                        output_buffer += text
                        
                        clean_text = self.strip_ansi(output_buffer)
                        clean_output = clean_text
                        
                        # Log meaningful updates
                        if clean_text and len(clean_text.strip()) > 0:
                             # Use repr to show hidden chars, truncate for log clarity
                             logger.info(f"PTY Update: {clean_text[:100]!r}...")
                        
                        last_output_time = time.time()
                        
                    except OSError as e:
                        logger.error(f"Error reading from PTY: {e}")
                        break
                
                if prompt_callback:
                    idle_time = time.time() - last_output_time
                    
                    if self._is_prompt(clean_output, idle_time):
                        logger.info(f"Detected interactive prompt: {clean_output[-200:]}")
                        try:
                            response = await prompt_callback(clean_output)
                            if response:
                                logger.info(f"Sending response to prompt: {response.strip()}")
                                os.write(master_fd, response.encode())
                                output_buffer = ""
                                clean_output = ""
                                # Reset cache on new interaction
                                self._message_cache = {} 
                                last_output_time = time.time()
                        except Exception as e:
                            logger.error(f"Error in prompt callback: {e}", exc_info=True)
                
                if output_callback and clean_output:
                    current_time = time.time()
                    # Only send if enough time passed
                    if current_time - last_callback_time >= CALLBACK_INTERVAL:
                        if not self._is_animation_frame(clean_output):
                            # TTL / Expiration Logic
                            # specific_content_key = hash(clean_output) # Simple hash for cache key
                            content_key = clean_output
                            
                            last_sent_time = self._message_cache.get(content_key, 0)
                            
                            # If message is new OR expired (TTL=60s)
                            if (current_time - last_sent_time) > 60:
                                try:
                                    await output_callback(clean_output)
                                    last_callback_time = current_time
                                    self._message_cache[content_key] = current_time
                                    
                                    # Periodic cache cleanup (simple)
                                    if len(self._message_cache) > 100:
                                        self._message_cache = {
                                            k: v for k, v in self._message_cache.items() 
                                            if current_time - v < 60
                                        }
                                except Exception as e:
                                    logger.error(f"Error in output callback: {e}")
                            else:
                                # Message content is identical to one sent recently (<60s)
                                pass 
                        else:
                            logger.debug("Skipping animation frame")
            
            try:
                while True:
                    ready, _, _ = select.select([master_fd], [], [], 0.1)
                    if not ready: break
                    data = os.read(master_fd, 4096)
                    if not data: break
                    text = data.decode('utf-8', errors='replace')
                    output_buffer += text
                    clean_output = self.strip_ansi(output_buffer)
            except:
                pass
            
            if output_callback and clean_output:
                try:
                    await output_callback(clean_output)
                except:
                    pass
            
            returncode = process.wait(timeout=5)
            success = (returncode == 0)
            
            if not success:
                return {
                    "success": False,
                    "output": clean_output,
                    "error": clean_output or f"Command failed with return code {returncode}",
                    "returncode": returncode
                }
            
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
