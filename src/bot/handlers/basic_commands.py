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
            "I'm your AI coding assistant powered by Claude Code CLI and OpenCode CLI.\n"
            "Use your authenticated account or OpenRouter models.\n\n"
            "**Available Commands:**\n"
            "/code <instruction> - Execute an AI coding instruction\n"
            "/agents - Select AI agent (Claude Code or OpenCode)\n"
            "/model - Select AI model\n"
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
            "• `/code <instruction>` - Execute coding instruction\n\n"
            "• `/agents [claude|opencode]` - Select AI agent\n"
            "  • claude: Claude Code CLI (models: sonnet, opus, haiku)\n"
            "  • opencode: OpenCode CLI (recommended: **GLM-4.7**, also glm-4)\n\n"
            "• `/model [name]` - Select AI model\n"
            "  Claude: sonnet, opus, haiku\n"
            "  OpenCode: glm-4.7, glm-4, deepseek-coder\n\n"
            "• `/bypass [on|off]` - Toggle bypass mode\n"
            "  ON: Clean output, auto-approved permissions\n"
            "  OFF: Interactive permission prompts\n\n"
            "• `/browse [path]` - Browse and select working directory\n\n"
            "• `/session new/clear/info` - Manage session\n\n"
            "• `/status` - Check backend availability\n\n"
            "**Note:** If selected CLI unavailable, auto-switches to available CLI"
        )
        
        await update.message.reply_text(help_message, parse_mode="Markdown")

    async def stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stop command."""
        if not await self.auth.check_auth(update, context):
            return
            
        user_id = update.effective_user.id
        logger.info(f"User {user_id} requested to stop execution")
        
        stopped = await self.orchestrator.stop_execution(user_id)
        
        if stopped:
            await update.message.reply_text("🛑 **Execution stopped.**", parse_mode="Markdown")
        else:
            await update.message.reply_text("ℹ️ No active execution to stop.")

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
        opencode_available = await self.orchestrator.check_opencode_availability()
        openrouter_available = await self.orchestrator.check_openrouter_availability()

        # Check session settings
        session = self.session_manager.get_session(user_id)
        if not session:
            await update.message.reply_text("ℹ️ No active session. Use `/session new` to create one.")
            return

        # Determine which backend will actually be used
        from src.claude.session_manager import OPENCODE_DEFAULT_MODEL
        actual_agent = session.agent_type
        actual_model = session.model
        warning_note = ""

        # If selected CLI unavailable, show what will actually be used
        if actual_agent == "opencode" and not opencode_available:
            if claude_available:
                actual_agent = "claude"
                actual_model = session.model if session.model not in ["sonnet", "opus", "haiku"] else "sonnet"
                warning_note = f"\n⚠️ OpenCode CLI unavailable. Using Claude Code CLI with model `{actual_model}`\n"
            elif openrouter_available:
                actual_agent = "openrouter"
                warning_note = f"\n⚠️ OpenCode CLI unavailable. Using OpenRouter API\n"
        elif actual_agent == "claude" and not claude_available:
            if opencode_available:
                actual_agent = "opencode"
                actual_model = session.model if session.model.startswith("glm") else OPENCODE_DEFAULT_MODEL
                warning_note = f"\n⚠️ Claude Code CLI unavailable. Using OpenCode CLI with model `{OPENCODE_DEFAULT_MODEL}`\n"
            elif openrouter_available:
                actual_agent = "openrouter"
                warning_note = f"\n⚠️ Claude Code CLI unavailable. Using OpenRouter API\n"

        # Show status
        agent_names = {
            "claude": "Claude Code CLI",
            "opencode": "OpenCode CLI",
            "openrouter": "OpenRouter API"
        }

        status_message = "🔍 **Backend Status**\n\n"
        status_message += f"Claude Code CLI: {'✅ Available' if claude_available else '❌ Unavailable'}\n"
        status_message += f"OpenCode CLI: {'✅ Available' if opencode_available else '❌ Unavailable'}\n"
        status_message += f"OpenRouter API: {'✅ Available' if openrouter_available else '❌ Unavailable'}\n"
        status_message += f"\n**Active Session:**\n"
        status_message += f"Agent: `{agent_names.get(actual_agent, actual_agent)}`\n"
        status_message += f"Model: `{actual_model}`\n"
        status_message += f"Bypass Mode: {'🚀 ON (clean output)' if session.bypass_mode else '🔒 OFF (interactive)'}\n"

        if warning_note:
            status_message += f"{warning_note}"
        elif actual_agent != session.agent_type:
            status_message += f"\nℹ️ Selected `{agent_names.get(session.agent_type, session.agent_type)}` but using `{agent_names.get(actual_agent, actual_agent)}` (unavailable)\n"

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
                    "• ⚠️ AI can execute any action without confirmation",
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
                "• ⚠️ AI can execute any action without confirmation\n\n"
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
        """Handle /model command - select AI model."""
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
            label = f"{'✓ ' if model_id == current_model else ''}{model_id}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"model_{model_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"🤖 *Select AI Model*\n\n"
            f"Current: `{current_model}`\n\n"
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

    async def agents(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /agents command - select AI agent (Claude Code or OpenCode)."""
        if not await self.auth.check_auth(update, context):
            return

        user_id = update.effective_user.id

        # Get current agent type
        current_agent = self.session_manager.get_agent_type(user_id)

        # If agent specified as argument, set it directly
        if context.args:
            agent_arg = context.args[0].lower()

            if agent_arg in ["claude", "claude-code"]:
                self.session_manager.set_agent_type(user_id, "claude")
                await update.message.reply_text(
                    "✅ **Agent set to Claude Code CLI**\n\n"
                    "• Models: sonnet, opus, haiku\n"
                    "• Interactive permission support\n"
                    "• Official Claude CLI",
                    parse_mode="Markdown"
                )
                return
            elif agent_arg in ["opencode", "open-code"]:
                self.session_manager.set_agent_type(user_id, "opencode")
                await update.message.reply_text(
                    "✅ **Agent set to OpenCode CLI**\n\n"
                    "• Recomended model: GLM-4.7\n"
                    "• Multi-provider support\n"
                    "• Alternative to Claude CLI",
                    parse_mode="Markdown"
                )
                return
            else:
                await update.message.reply_text(
                    f"❌ Invalid agent: {agent_arg}\n\n"
                    "Use: /agents [claude|opencode]",
                    parse_mode="Markdown"
                )
                return

        # Check availability
        claude_available = await self.orchestrator.check_claude_availability()
        opencode_available = await self.orchestrator.check_opencode_availability()

        # Show agent selection with inline keyboard
        keyboard = []
        agents = {
            "claude": f"Claude Code {'✅' if claude_available else '❌'}",
            "opencode": f"OpenCode {'✅' if opencode_available else '❌'}"
        }

        for agent_id, agent_name in agents.items():
            label = f"{'✓ ' if agent_id == current_agent else ''}{agent_name}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"agent_{agent_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"🤖 *Select AI Agent*\n\n"
            f"Current: `{agents.get(current_agent, current_agent)}`\n\n"
            "*Claude Code CLI* (default):\n"
            "• Models: sonnet, opus, haiku\n"
            "• Official Claude CLI with permissions\n"
            f"• Status: {'✅ Available' if claude_available else '❌ Unavailable'}\n\n"
            "*OpenCode CLI*:\n"
            "• Recommended: GLM-4.7 (also supports glm-4)\n"
            "• Multi-provider (GLM, DeepSeek, etc)\n"
            f"• Status: {'✅ Available' if opencode_available else '❌ Unavailable'}\n\n"
            "Choose an agent (unreachable CLIs auto-switch):",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def handle_agents_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle agent selection callback."""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        agent_id = query.data.replace("agent_", "")

        agent_names = {
            "claude": "Claude Code CLI",
            "opencode": "OpenCode CLI"
        }

        if agent_id in agent_names:
            self.session_manager.set_agent_type(user_id, agent_id)
            agent_name = agent_names[agent_id]

            await query.edit_message_text(
                f"✅ **Agent set to: {agent_name}**\n\n"
                f"Using {agent_id} CLI for AI assistance.",
                parse_mode="Markdown"
            )
            logger.info(f"User {user_id} selected agent: {agent_id}")
        else:
            await query.edit_message_text(
                f"❌ Invalid agent selected",
                parse_mode="Markdown"
            )