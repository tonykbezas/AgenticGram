# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgenticGram is a Telegram bot that bridges remote control to AI CLI tools (Claude Code, OpenRouter). It's designed for lightweight servers like Raspberry Pi and provides an interactive permission system for file operations.

## Commands

```bash
# Run the bot
python -m src.bot

# Run as systemd service (if installed)
sudo systemctl start agenticgram

# Diagnostic check
./scripts/diagnose.sh

# Installation
./scripts/install.sh
```

## Architecture

```
Telegram User → Bot (telegram.ext.Application)
      ↓
[Auth Middleware] → [Stale Filter]
      ↓
Command Handlers
      ↓
Orchestrator
      ↓
┌─────┴──────┐
Claude Code   OpenRouter
(Primary)     (Fallback)
      ↓
PTY Wrapper → Permission Callbacks → User Approval (Telegram UI)
```

**Core Components:**
- `src/bot/bot.py` - Main bot orchestration, initializes SessionManager, Orchestrator, DirectoryBrowser, PermissionHandler
- `src/orchestrator.py` - Backend routing: tries Claude Code first, falls back to OpenRouter on quota/error. Checks session.bypass_mode to select execution method
- `src/claude/claude_client.py` - CLI execution with two modes:
  - `execute_command()` - PTY-based interactive mode with permission callbacks
  - `execute_with_pipes()` - Pipes mode with `--permission-mode bypassPermissions` for clean output
- `src/claude/pty_wrapper.py` - PTY-based subprocess execution for interactive Claude CLI
- `src/claude/session_manager.py` - SQLite persistence for sessions (includes bypass_mode flag) and permissions
- `src/telegram/message_sender.py` - Streaming message updates with debouncing, ANSI stripping, message splitting

**Handler Structure:**
- `src/bot/handlers/basic_commands.py` - /start, /help, /session, /status, /bypass
- `src/bot/handlers/code_commands.py` - /code command execution
- `src/bot/handlers/browser_commands.py` - /browse, /trust directory navigation
- `src/bot/handlers/permission_handler.py` - Interactive permission request handling
- `src/bot/handlers/message_handler.py` - File upload handling

**Middleware:**
- `src/bot/middleware/auth.py` - User authentication via ALLOWED_TELEGRAM_IDS
- `src/bot/middleware/stale_filter.py` - Filters old/stale Telegram updates

## Key Implementation Details

**Execution Modes:** Two modes controlled by `/bypass` command (stored in session.bypass_mode):

| Mode | Method | Flags | Output | Permissions |
|------|--------|-------|--------|-------------|
| PTY (default) | `execute_command()` | None | TUI artifacts (cleaned via regex) | Interactive prompts |
| Bypass | `execute_with_pipes()` | `-p --permission-mode bypassPermissions --output-format stream-json` | Clean JSON stream | All auto-approved |

**PTY Execution:** Uses pseudo-terminals to capture interactive Claude CLI output. Complex ANSI escape code regex handles OSC, CSI, DCS sequences. TUI artifact cleaning removes borders, spinners, headers.

**Pipes Execution:** Uses subprocess pipes with Claude's print mode. Output is clean JSON stream parsed line-by-line. No TUI artifacts, no interactive prompts.

**Permission System:** (PTY mode only) Detects interactive prompts via regex, auto-approves directory trust prompts, forwards yes/no and menu prompts to user via Telegram inline buttons. Uses `asyncio.Future` with 5-minute timeout.

**Session Management:** One session per Telegram user with separate workspace directories (`{WORK_DIR}/{telegram_id}/`). SQLite database with sessions (includes bypass_mode) and permissions tables. Auto-cleanup of 24+ hour old sessions.

**Message Handling:** Respects Telegram's 4096 character limit. Debounces updates with 1.0 second cooldown. Splits long outputs across multiple messages.

**Model Cascade:** Claude Code CLI (primary) → OpenRouter fallback (claude-3.5-sonnet → qwen-2.5-coder → deepseek-coder → llama-3.1-70b)

## Code Quality Rules

**300-line file limit:** No source file should exceed 300 lines. If a file exceeds this limit, refactor by:
- Splitting into smaller logical modules
- Extracting classes/functions into separate files
- Moving utilities to a `utils` module

## Environment Configuration

**Required:**
- `TELEGRAM_BOT_TOKEN` - From @BotFather
- `ALLOWED_TELEGRAM_IDS` - Comma-separated authorized user IDs

**Key Optional:**
- `OPENROUTER_API_KEY` - For fallback support
- `WORK_DIR` (default: `./workspace`) - Session working directories
- `PERMISSION_TIMEOUT_MINUTES` (default: 5) - Permission approval timeout
- `MAX_SESSION_AGE_HOURS` (default: 24) - Session expiration

## Dependencies

- `python-telegram-bot>=20.0` - Async Telegram bot framework
- `python-dotenv>=1.0.0` - Environment variable management
- `aiohttp>=3.9.0` - Async HTTP client for OpenRouter
- `aiofiles>=23.0.0` - Async file operations
- Claude Code CLI (Node.js, installed via `npm install -g @anthropic-ai/claude-code`)
