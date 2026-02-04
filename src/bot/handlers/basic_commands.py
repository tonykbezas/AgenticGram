
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.bot.middleware.auth import AuthMiddleware
from src.claude.session_manager import CLAUDE_MODELS

logger = logging.getLogger(__name__)

class BasicCommands:
    def __init__(self, auth_middleware: AuthMiddleware, session_manager, orchestrator):
        self.auth = auth_middleware
        self.session_manager = session_manager
        self.orchestrator = orchestrator

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not await self.auth.check_auth(update, context):
            return
        
        user_id = update.effective_user.id
        welcome_message = (
            "🤖 **Welcome to AgenticGram!**\n\n"
            "I'm your AI coding assistant bridge. I can execute commands via Claude Code CLI "
            "or fallback to OpenRouter when needed.\n\n"
            "**Available Commands:**\n"
            "/code <instruction> - Execute an AI coding instruction\n"
            "/model - Select Claude model (sonnet/opus/haiku)\n"
            "/bypass - Toggle bypass mode (clean output, no prompts)\n"
            "/browse - Browse and select working directory\n"
            "/session - Manage your session (new/clear/info)\n"
            "/status - Check backend availability\n"
            "/help - Show this help message\n\n"
            "You can also send me code files (.py, .sql, .js) and I'll save them to your workspace!"
        )
        
        await update.message.reply_text(welcome_message, parse_mode="Markdown")
        logger.info(f"User {user_id} started the bot")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not await self.auth.check_auth(update, context):
            return
        
        help_message = (
            "📚 **AgenticGram Help**\n\n"
            "**Commands:**\n"
            "• `/code <instruction>` - Execute coding instruction\n"
            "  Example: `/code Create a Python function to calculate fibonacci`\n\n"
            "• `/model [name]` - Select Claude model\n"
            "  Options: sonnet (balanced), opus (most capable), haiku (fastest)\n"
            "  Or use full model name like `claude-sonnet-4-5-20250929`\n\n"
            "• `/bypass [on|off]` - Toggle bypass mode\n"
            "  ON: Uses pipes with clean output, all permissions auto-approved\n"
            "  OFF: Uses PTY with interactive permission prompts\n\n"
            "• `/browse [path]` - Browse and select working directory\n"
            "  Navigate through directories with inline buttons\n\n"
            "• `/trust [directory]` - Trust a directory for Claude CLI\n"
            "  Prevents permission prompts for the specified directory\n\n"
            "• `/session new` - Start a new session\n"
            "• `/session clear` - Clear current session\n"
            "• `/session info` - Show session information\n\n"
            "• `/status` - Check AI backend availability and current mode\n\n"
            "**File Uploads:**\n"
            "Send me code files and I'll save them to your workspace.\n"
            "Supported: .py, .sql, .js, .txt, .json, .md"
        )
        
        await update.message.reply_text(help_message, parse_mode="Markdown")

    async def session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /session command."""
        if not await self.auth.check_auth(update, context):
            return
        
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "Usage:\n"
                "/session new - Create new session\n"
                "/session clear - Clear current session\n"
                "/session info - Show session info"
            )
            return
        
        action = context.args[0].lower()
        
        if action == "new":
            session = self.session_manager.create_session(user_id)
            await update.message.reply_text(
                f"✅ New session created!\n"
                f"Session ID: `{session.session_id}`\n"
                f"Workspace: `{session.work_dir}`",
                parse_mode="Markdown"
            )
        
        elif action == "clear":
            if self.session_manager.delete_session(user_id):
                await update.message.reply_text("✅ Session cleared!")
            else:
                await update.message.reply_text("ℹ️ No active session to clear.")
        
        elif action == "info":
            session = self.session_manager.get_session(user_id)
            if session:
                await update.message.reply_text(
                    f"📊 **Session Info**\n\n"
                    f"Session ID: `{session.session_id}`\n"
                    f"Created: {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"Last used: {session.last_used.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"Messages: {session.message_count}\n"
                    f"Workspace: `{session.work_dir}`",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("ℹ️ No active session. Use `/session new` to create one.")
        
        else:
            await update.message.reply_text("❌ Unknown action. Use: new, clear, or info")

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        if not await self.auth.check_auth(update, context):
            return

        await update.message.chat.send_action("typing")

        user_id = update.effective_user.id

        # Check backend availability
        claude_available = await self.orchestrator.check_claude_availability()
        openrouter_available = await self.orchestrator.check_openrouter_availability()

        # Check session settings
        session = self.session_manager.get_session(user_id)
        bypass_enabled = session.bypass_mode if session else False
        current_model = session.model if session else "sonnet"

        status_message = "🔍 **Backend Status**\n\n"
        status_message += f"Claude Code CLI: {'✅ Available' if claude_available else '❌ Unavailable'}\n"
        status_message += f"OpenRouter API: {'✅ Available' if openrouter_available else '❌ Unavailable'}\n"
        status_message += f"\n**Session Settings:**\n"
        status_message += f"Model: `{current_model}`\n"
        status_message += f"Bypass Mode: {'🚀 ON (pipes)' if bypass_enabled else '🔒 OFF (PTY)'}\n"

        await update.message.reply_text(status_message, parse_mode="Markdown")

    async def bypass(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /bypass command - toggle bypass mode."""
        if not await self.auth.check_auth(update, context):
            return

        user_id = update.effective_user.id

        # Check for explicit on/off argument
        if context.args:
            arg = context.args[0].lower()
            if arg in ["on", "1", "true", "yes"]:
                self.session_manager.set_bypass_mode(user_id, True)
                await update.message.reply_text(
                    "🚀 **Bypass Mode: ON**\n\n"
                    "Using pipes with `--permission-mode bypassPermissions`\n"
                    "• Clean output (no TUI artifacts)\n"
                    "• All permissions auto-approved\n"
                    "• ⚠️ Claude can execute any action without confirmation",
                    parse_mode="Markdown"
                )
                return
            elif arg in ["off", "0", "false", "no"]:
                self.session_manager.set_bypass_mode(user_id, False)
                await update.message.reply_text(
                    "🔒 **Bypass Mode: OFF**\n\n"
                    "Using PTY (interactive mode)\n"
                    "• Interactive permission prompts\n"
                    "• You approve/deny each action",
                    parse_mode="Markdown"
                )
                return

        # Toggle mode
        success, new_mode = self.session_manager.toggle_bypass_mode(user_id)

        if new_mode:
            await update.message.reply_text(
                "🚀 **Bypass Mode: ON**\n\n"
                "Using pipes with `--permission-mode bypassPermissions`\n"
                "• Clean output (no TUI artifacts)\n"
                "• All permissions auto-approved\n"
                "• ⚠️ Claude can execute any action without confirmation\n\n"
                "Use `/bypass off` to disable.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "🔒 **Bypass Mode: OFF**\n\n"
                "Using PTY (interactive mode)\n"
                "• Interactive permission prompts\n"
                "• You approve/deny each action\n\n"
                "Use `/bypass on` to enable.",
                parse_mode="Markdown"
            )

        logger.info(f"User {user_id} toggled bypass mode to: {new_mode}")

    async def model(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /model command - select Claude model."""
        if not await self.auth.check_auth(update, context):
            return

        user_id = update.effective_user.id

        # Get current model
        current_model = self.session_manager.get_model(user_id)

        # If model specified as argument, set it directly
        if context.args:
            model_arg = context.args[0].lower()

            # Check if valid model
            if model_arg in CLAUDE_MODELS:
                self.session_manager.set_model(user_id, model_arg)
                model_desc = CLAUDE_MODELS[model_arg]
                await update.message.reply_text(
                    f"✅ **Model set to: {model_arg}**\n\n{model_desc}",
                    parse_mode="Markdown"
                )
                return
            else:
                # Could be a full model name like claude-sonnet-4-5-20250929
                self.session_manager.set_model(user_id, model_arg)
                await update.message.reply_text(
                    f"✅ **Model set to:** `{model_arg}`\n\n"
                    "Note: Using custom model name. Make sure it's valid.",
                    parse_mode="Markdown"
                )
                return

        # Show model selection with inline keyboard
        keyboard = []
        for model_id, model_desc in CLAUDE_MODELS.items():
            # Mark current model
            label = f"{'✓ ' if model_id == current_model else ''}{model_id}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"model_{model_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"🤖 **Select Claude Model**\n\n"
            f"Current: **{current_model}**\n\n"
            "Choose a model:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def handle_model_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle model selection callback."""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        model_id = query.data.replace("model_", "")

        if model_id in CLAUDE_MODELS:
            self.session_manager.set_model(user_id, model_id)
            model_desc = CLAUDE_MODELS[model_id]

            await query.edit_message_text(
                f"✅ **Model set to: {model_id}**\n\n{model_desc}",
                parse_mode="Markdown"
            )
            logger.info(f"User {user_id} selected model: {model_id}")

    async def new_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /new command - start a fresh conversation (no context)."""
        if not await self.auth.check_auth(update, context):
            return

        user_id = update.effective_user.id

        # Mark that next message should NOT use --continue
        context.user_data['new_conversation'] = True

        await update.message.reply_text(
            "🆕 **New conversation started**\n\n"
            "Your next message will start a fresh conversation without previous context.\n"
            "Send your instruction now.",
            parse_mode="Markdown"
        )

        logger.info(f"User {user_id} started new conversation")
