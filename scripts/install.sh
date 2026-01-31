#!/bin/bash

# AgenticGram Installation Script
# Automated installation for Debian/Ubuntu/Raspbian

set -e  # Exit on error

echo "========================================="
echo "  AgenticGram Installation Script"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    echo -e "${RED}Please do not run this script as root${NC}"
    exit 1
fi

# Function to print colored messages
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# Check system requirements
echo "Checking system requirements..."

# Check Python version
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
    REQUIRED_VERSION="3.9"
    
    if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" = "$REQUIRED_VERSION" ]; then
        print_success "Python $PYTHON_VERSION found"
    else
        print_error "Python 3.9+ required, found $PYTHON_VERSION"
        exit 1
    fi
else
    print_error "Python 3 not found"
    exit 1
fi

# Check Node.js
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
    if [ "$NODE_VERSION" -ge 18 ]; then
        print_success "Node.js $(node --version) found"
    else
        print_info "Node.js 18+ recommended, found v$NODE_VERSION"
    fi
else
    print_info "Node.js not found. Installing..."
    
    # Install Node.js using NodeSource repository
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
    
    print_success "Node.js installed"
fi

# Check npm
if ! command -v npm &> /dev/null; then
    print_error "npm not found"
    exit 1
fi

# Install Claude Code CLI
echo ""
echo "Installing Claude Code CLI..."

if command -v claude-code &> /dev/null; then
    print_info "Claude Code already installed"
else
    # Try without sudo first (works with nvm/user-installed npm)
    if npm install -g @anthropic-ai/claude-code &> /dev/null; then
        print_success "Claude Code CLI installed (user-level)"
    else
        # Fallback to sudo if user-level install fails
        print_info "Trying with sudo..."
        if sudo npm install -g @anthropic-ai/claude-code; then
            print_success "Claude Code CLI installed (system-level)"
        else
            print_error "Claude Code CLI installation failed"
            print_info "You can install it manually later with: npm install -g @anthropic-ai/claude-code"
            print_info "Continuing with installation..."
        fi
    fi
fi

# Verify Claude Code installation
if command -v claude-code &> /dev/null; then
    print_success "Claude Code CLI verified"
else
    print_info "Claude Code CLI not found, but continuing installation"
    print_info "The bot will use OpenRouter fallback if Claude Code is not available"
fi

# Create Python virtual environment
echo ""
echo "Setting up Python environment..."

if [ -d "venv" ]; then
    print_info "Virtual environment already exists"
else
    python3 -m venv venv
    print_success "Virtual environment created"
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip > /dev/null 2>&1

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip install -r requirements.txt
print_success "Python dependencies installed"

# Create necessary directories
echo ""
echo "Creating directories..."

mkdir -p workspace
mkdir -p logs
print_success "Directories created"

# Setup configuration
echo ""
echo "Setting up configuration..."

if [ -f ".env" ]; then
    print_info ".env file already exists, skipping"
else
    cp config/.env.example .env
    print_success "Created .env file from template"
    
    echo ""
    print_info "Please edit .env file with your configuration:"
    echo "  - TELEGRAM_BOT_TOKEN: Get from @BotFather on Telegram"
    echo "  - ALLOWED_TELEGRAM_IDS: Your Telegram user ID (comma-separated)"
    echo "  - OPENROUTER_API_KEY: Optional, for fallback support"
    echo ""
    
    read -p "Press Enter to continue..."
fi

# Setup systemd service (optional)
echo ""
read -p "Do you want to install as a systemd service? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    CURRENT_DIR=$(pwd)
    CURRENT_USER=$(whoami)
    
    # Create service file from template
    sudo tee /etc/systemd/system/agenticgram.service > /dev/null <<EOF
[Unit]
Description=AgenticGram Telegram Bot
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
Environment="PATH=$CURRENT_DIR/venv/bin:/usr/local/bin:/usr/bin"
ExecStart=$CURRENT_DIR/venv/bin/python -m src.bot
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    # Reload systemd
    sudo systemctl daemon-reload
    
    print_success "Systemd service installed"
    print_info "To start the service: sudo systemctl start agenticgram"
    print_info "To enable on boot: sudo systemctl enable agenticgram"
    print_info "To view logs: sudo journalctl -u agenticgram -f"
fi

# Verify installation
echo ""
echo "Verifying installation..."

# Check if all required files exist
REQUIRED_FILES=("src/bot.py" "src/orchestrator.py" "src/claude_handler.py" "requirements.txt" ".env")
ALL_EXIST=true

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        print_success "$file exists"
    else
        print_error "$file missing"
        ALL_EXIST=false
    fi
done

echo ""
echo "========================================="
if [ "$ALL_EXIST" = true ]; then
    print_success "Installation completed successfully!"
    echo ""
    echo "Next steps:"
    echo "1. Edit .env file with your credentials"
    echo "2. Run the bot: python -m src.bot"
    echo "   Or use systemd: sudo systemctl start agenticgram"
else
    print_error "Installation incomplete. Please check errors above."
    exit 1
fi
echo "========================================="
