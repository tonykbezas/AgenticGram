#!/bin/bash
# AgenticGram Diagnostic Script
# Verifica la configuración y disponibilidad de Claude CLI

echo "🔍 AgenticGram Diagnostic Tool"
echo "=============================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to check command
check_command() {
    if command -v "$1" &> /dev/null; then
        echo -e "${GREEN}✓${NC} $1 is installed"
        return 0
    else
        echo -e "${RED}✗${NC} $1 is NOT installed"
        return 1
    fi
}

# Function to check file
check_file() {
    if [ -f "$1" ]; then
        echo -e "${GREEN}✓${NC} $1 exists"
        return 0
    else
        echo -e "${RED}✗${NC} $1 NOT found"
        return 1
    fi
}

echo -e "${BLUE}1. Checking Python environment...${NC}"
check_command python3
check_command pip3
python3 --version
echo ""

echo -e "${BLUE}2. Checking Claude CLI...${NC}"
if check_command claude; then
    echo "   Version: $(claude --version 2>&1)"
    echo "   Path: $(which claude)"
else
    echo -e "${YELLOW}   Hint: Install with: npm install -g @anthropic-ai/claude-code${NC}"
fi
echo ""

echo -e "${BLUE}3. Checking configuration files...${NC}"
# Check for .env in root directory (where load_dotenv() looks by default)
if check_file ".env"; then
    echo "   Checking .env contents..."
    
    # Check for required variables
    if grep -q "TELEGRAM_BOT_TOKEN" .env; then
        TOKEN=$(grep "TELEGRAM_BOT_TOKEN" .env | cut -d'=' -f2)
        if [ "$TOKEN" != "your_bot_token_here" ] && [ -n "$TOKEN" ]; then
            echo -e "   ${GREEN}✓${NC} TELEGRAM_BOT_TOKEN is set"
        else
            echo -e "   ${RED}✗${NC} TELEGRAM_BOT_TOKEN not configured"
        fi
    fi
    
    if grep -q "CLAUDE_CODE_PATH" .env; then
        CLAUDE_PATH=$(grep "CLAUDE_CODE_PATH" .env | cut -d'=' -f2)
        if [ -n "$CLAUDE_PATH" ]; then
            echo -e "   ${GREEN}✓${NC} CLAUDE_CODE_PATH is set to: $CLAUDE_PATH"
        else
            echo -e "   ${GREEN}✓${NC} CLAUDE_CODE_PATH not set (will use 'claude' from PATH)"
        fi
    else
        echo -e "   ${GREEN}✓${NC} CLAUDE_CODE_PATH not set (will use 'claude' from PATH)"
    fi
    
    if grep -q "OPENROUTER_API_KEY" .env; then
        OR_KEY=$(grep "OPENROUTER_API_KEY" .env | cut -d'=' -f2)
        if [ "$OR_KEY" != "your_openrouter_key_here" ] && [ -n "$OR_KEY" ]; then
            echo -e "   ${GREEN}✓${NC} OPENROUTER_API_KEY is set (fallback available)"
        else
            echo -e "   ${YELLOW}⚠${NC}  OPENROUTER_API_KEY not configured (no fallback)"
        fi
    fi
else
    echo -e "${RED}✗${NC} .env NOT found in root directory"
    echo -e "   ${YELLOW}Create .env from config/.env.example:${NC}"
    echo "   cp config/.env.example .env"
    echo "   nano .env  # Edit with your tokens"
fi
echo ""

echo -e "${BLUE}4. Checking bot process...${NC}"
# Check systemd first
if systemctl is-active --quiet agenticgram 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Bot is running (systemd service)"
    echo "   Service: agenticgram"
    echo "   Status: $(systemctl is-active agenticgram)"
    echo "   To restart: sudo systemctl restart agenticgram"
    echo "   To view logs: sudo journalctl -u agenticgram -f"
elif pgrep -f "python.*bot.py" > /dev/null; then
    echo -e "${GREEN}✓${NC} Bot is running (manual process)"
    echo "   PID: $(pgrep -f 'python.*bot.py')"
    echo "   Command: $(ps aux | grep 'python.*bot.py' | grep -v grep | awk '{print $11, $12, $13}')"
else
    echo -e "${YELLOW}⚠${NC}  Bot is NOT running"
    echo "   Start with: sudo systemctl start agenticgram"
    echo "   Or manually: python3 -m src.bot"
fi
echo ""

echo -e "${BLUE}5. Testing Claude CLI directly...${NC}"
if command -v claude &> /dev/null; then
    echo "   Running: claude --version"
    claude --version 2>&1
    echo ""
    echo "   Testing simple command..."
    echo "   Running: echo 'hello' | claude 'respond with just the word ok'"
    timeout 10s bash -c "echo 'hello' | claude 'respond with just the word ok'" 2>&1 | head -n 5
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        echo -e "   ${GREEN}✓${NC} Claude CLI is working!"
    elif [ $EXIT_CODE -eq 124 ]; then
        echo -e "   ${YELLOW}⚠${NC}  Claude CLI timed out (might need authentication)"
    else
        echo -e "   ${RED}✗${NC} Claude CLI failed with exit code: $EXIT_CODE"
    fi
else
    echo -e "   ${RED}✗${NC} Cannot test - Claude CLI not found"
fi
echo ""

echo -e "${BLUE}6. Checking logs...${NC}"
if [ -f "agenticgram.log" ]; then
    echo -e "${GREEN}✓${NC} Log file found: agenticgram.log"
    echo "   Last 5 lines:"
    tail -n 5 agenticgram.log | sed 's/^/   /'
elif [ -f "/var/log/agenticgram.log" ]; then
    echo -e "${GREEN}✓${NC} Log file found: /var/log/agenticgram.log"
    echo "   Last 5 lines:"
    sudo tail -n 5 /var/log/agenticgram.log | sed 's/^/   /'
else
    echo -e "${YELLOW}⚠${NC}  No log file found"
    echo "   Check if bot is logging to stdout/stderr"
fi
echo ""

echo -e "${BLUE}7. Checking for errors in logs...${NC}"
if [ -f "agenticgram.log" ]; then
    ERROR_COUNT=$(grep -c "ERROR" agenticgram.log 2>/dev/null || echo "0")
    WARNING_COUNT=$(grep -c "WARNING" agenticgram.log 2>/dev/null || echo "0")
    echo "   Errors: $ERROR_COUNT"
    echo "   Warnings: $WARNING_COUNT"
    
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo ""
        echo "   Last 3 errors:"
        grep "ERROR" agenticgram.log | tail -n 3 | sed 's/^/   /'
    fi
elif systemctl is-active --quiet agenticgram 2>/dev/null; then
    echo "   Checking systemd logs..."
    ERROR_COUNT=$(sudo journalctl -u agenticgram | grep -c "ERROR" || echo "0")
    echo "   Errors in systemd logs: $ERROR_COUNT"
    
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo ""
        echo "   Last 3 errors:"
        sudo journalctl -u agenticgram | grep "ERROR" | tail -n 3 | sed 's/^/   /'
    fi
fi
echo ""

echo -e "${BLUE}8. Recommendations:${NC}"
echo ""

if ! command -v claude &> /dev/null; then
    echo -e "${YELLOW}→${NC} Install Claude CLI:"
    echo "   npm install -g @anthropic-ai/claude-code"
    echo ""
fi

if [ ! -f ".env" ]; then
    echo -e "${YELLOW}→${NC} Create configuration:"
    echo "   cp config/.env.example .env"
    echo "   nano .env  # Edit with your tokens"
    echo ""
fi

# Check if running as systemd service
if systemctl is-active --quiet agenticgram 2>/dev/null; then
    echo -e "${YELLOW}→${NC} Bot is running as systemd service. To apply code changes:"
    echo "   git pull origin main"
    echo "   sudo systemctl restart agenticgram"
    echo "   sudo journalctl -u agenticgram -f  # View logs"
    echo ""
elif ! pgrep -f "python.*bot.py" > /dev/null; then
    echo -e "${YELLOW}→${NC} Start the bot:"
    echo "   sudo systemctl start agenticgram  # If using systemd"
    echo "   python3 -m src.bot  # Or run manually"
    echo ""
fi

# Check for timeout errors
if [ -f "agenticgram.log" ]; then
    TIMEOUT_COUNT=$(grep -c "Timed out" agenticgram.log 2>/dev/null || echo "0")
elif systemctl is-active --quiet agenticgram 2>/dev/null; then
    TIMEOUT_COUNT=$(sudo journalctl -u agenticgram | grep -c "Timed out" 2>/dev/null || echo "0")
else
    TIMEOUT_COUNT=0
fi

if [ "$TIMEOUT_COUNT" -gt 0 ]; then
    echo -e "${RED}⚠${NC}  Found $TIMEOUT_COUNT timeout errors!"
    echo "   This was fixed in recent commits. Make sure to:"
    echo "   1. git pull origin main"
    echo "   2. sudo systemctl restart agenticgram"
    echo ""
fi

echo -e "${GREEN}Diagnostic complete!${NC}"
echo ""
echo "For more help, check the logs with:"
echo "  ./scripts/view_logs.sh"
