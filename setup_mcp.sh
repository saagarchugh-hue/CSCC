#!/bin/bash

# MCP Setup Script
# Configures Jira, Snowflake, and Notion MCP servers for Cursor and Claude Code

set -e

echo "🤖 MCP Server Setup"
echo "==================="
echo ""

# Check for Xcode Command Line Tools (required for many dev tools)
if ! xcode-select -p &> /dev/null; then
    echo "📦 Xcode Command Line Tools not found. Installing..."
    echo "   (A dialog may appear - click 'Install' to proceed)"
    xcode-select --install
    echo ""
    echo "⏳ Waiting for Xcode Command Line Tools installation..."
    echo "   Please complete the installation dialog, then press Enter to continue."
    read -p ""
fi

# Get user email
read -p "Enter your email (e.g., your.email@affirm.com): " USER_EMAIL

# Get username for paths
USERNAME=$(whoami)

# Create directories
echo ""
echo "📁 Creating directories..."
mkdir -p ~/mcp/snowflake
mkdir -p ~/.cursor
mkdir -p ~/.claude

# Find or install uvx
UVX_PATH=""
if command -v uvx &> /dev/null; then
    UVX_PATH=$(which uvx)
elif [ -f "/Users/${USERNAME}/Library/Python/3.9/bin/uvx" ]; then
    UVX_PATH="/Users/${USERNAME}/Library/Python/3.9/bin/uvx"
elif [ -f "/opt/homebrew/bin/uvx" ]; then
    UVX_PATH="/opt/homebrew/bin/uvx"
else
    echo "📦 Installing uv..."
    if command -v pip3 &> /dev/null; then
        pip3 install uv
        UVX_PATH="/Users/${USERNAME}/Library/Python/3.9/bin/uvx"
    elif command -v brew &> /dev/null; then
        brew install uv
        UVX_PATH="/opt/homebrew/bin/uvx"
    else
        echo "❌ Could not install uv. Please install manually: pip3 install uv"
        exit 1
    fi
fi

echo "📍 Using uvx at: $UVX_PATH"

# Create Snowflake config
echo "⚙️  Creating Snowflake config..."
cat > ~/mcp/snowflake/config.yaml << 'EOF'
other_services:
  query_manager: True
  semantic_manager: True

sql_statement_permissions:
  - Alter: False
  - Command: False
  - Comment: False
  - Commit: False
  - Create: True
  - Delete: False
  - Describe: True
  - Drop: False
  - Insert: False
  - Merge: False
  - Rollback: False
  - Select: True
  - Transaction: False
  - TruncateTable: False
  - Unknown: False
  - Update: False
  - Use: True
EOF

# Generate MCP config for Cursor (Notion without type: http)
CURSOR_MCP_CONFIG=$(cat << EOF
{
  "mcpServers": {
    "jira": {
      "type": "http",
      "url": "https://mcp.atlassian.com/v1/mcp"
    },
    "mcp-server-snowflake": {
      "command": "${UVX_PATH}",
      "args": [
        "snowflake-labs-mcp",
        "--account",
        "AFFIRM-AFFIRMUSEAST",
        "--user",
        "${USER_EMAIL}",
        "--authenticator",
        "externalbrowser",
        "--service-config-file",
        "/Users/${USERNAME}/mcp/snowflake/config.yaml"
      ]
    },
    "Notion": {
      "url": "https://mcp.notion.com/mcp",
      "headers": {}
    }
  }
}
EOF
)

# Generate MCP config for Claude Code (Notion WITH type: http for compatibility)
CLAUDE_MCP_CONFIG=$(cat << EOF
{
  "mcpServers": {
    "jira": {
      "type": "http",
      "url": "https://mcp.atlassian.com/v1/mcp"
    },
    "mcp-server-snowflake": {
      "command": "${UVX_PATH}",
      "args": [
        "snowflake-labs-mcp",
        "--account",
        "AFFIRM-AFFIRMUSEAST",
        "--user",
        "${USER_EMAIL}",
        "--authenticator",
        "externalbrowser",
        "--service-config-file",
        "/Users/${USERNAME}/mcp/snowflake/config.yaml"
      ]
    },
    "Notion": {
      "type": "http",
      "url": "https://mcp.notion.com/mcp",
      "headers": {}
    }
  }
}
EOF
)

# Write Cursor config
echo "📝 Writing Cursor config..."
echo "$CURSOR_MCP_CONFIG" > ~/.cursor/mcp.json

# Write Claude Code configs (both locations for compatibility)
echo "📝 Writing Claude Code configs..."

# 1. Write to ~/.claude/claude_desktop_config.json (older location)
echo "$CLAUDE_MCP_CONFIG" > ~/.claude/claude_desktop_config.json

# 2. Update ~/.claude.json (newer location) - merge with existing if present
if [ -f ~/.claude.json ]; then
    echo "   Found existing ~/.claude.json, merging MCP config..."
    # Use Python to merge JSON (available on macOS by default)
    python3 << PYTHON_SCRIPT
import json
import os

# Read existing config
with open(os.path.expanduser('~/.claude.json'), 'r') as f:
    try:
        existing = json.load(f)
    except json.JSONDecodeError:
        existing = {}

# MCP servers to add
new_mcp = {
    "jira": {
        "type": "http",
        "url": "https://mcp.atlassian.com/v1/mcp"
    },
    "mcp-server-snowflake": {
        "command": "${UVX_PATH}",
        "args": [
            "snowflake-labs-mcp",
            "--account",
            "AFFIRM-AFFIRMUSEAST",
            "--user",
            "${USER_EMAIL}",
            "--authenticator",
            "externalbrowser",
            "--service-config-file",
            "/Users/${USERNAME}/mcp/snowflake/config.yaml"
        ]
    },
    "Notion": {
        "type": "http",
        "url": "https://mcp.notion.com/mcp",
        "headers": {}
    }
}

# Merge - add or update mcpServers
if 'mcpServers' not in existing:
    existing['mcpServers'] = {}
existing['mcpServers'].update(new_mcp)

# Write back
with open(os.path.expanduser('~/.claude.json'), 'w') as f:
    json.dump(existing, f, indent=2)
PYTHON_SCRIPT
else
    # Create new file with just mcpServers
    echo "$CLAUDE_MCP_CONFIG" > ~/.claude.json
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Restart Cursor and/or Claude Code"
echo "  2. When prompted, authorize Jira and Notion in your browser"
echo "  3. For Snowflake, complete the SSO login when prompted"
echo ""
echo "⚠️  IMPORTANT: When authorizing Jira, you MUST uncheck 'Confluence'"
echo "   in the OAuth dialog. Confluence is checked by default — if you"
echo "   leave it checked, OAuth will fail."
echo ""
echo "Config files created:"
echo "  - ~/.cursor/mcp.json"
echo "  - ~/.claude/claude_desktop_config.json"
echo "  - ~/.claude.json"
echo "  - ~/mcp/snowflake/config.yaml"
