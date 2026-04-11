# Veritas MCP Server

Veritas exposes its trust layer as MCP tools for any MCP-compatible
LLM client (Claude desktop, Claude Code, or any MCP client).

## Installation

```bash
pip install -r requirements.txt  # includes mcp
```

## Claude Desktop configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "veritas": {
      "command": "python",
      "args": ["-m", "python.mcp"],
      "cwd": "/path/to/veritas",
      "env": {
        "VERITAS_DB_PATH": "/path/to/veritas/data/veritas.db"
      }
    }
  }
}
```

## Claude Code configuration

Add to your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "veritas": {
      "command": "python",
      "args": ["-m", "python.mcp"],
      "cwd": "/path/to/veritas",
      "env": {
        "VERITAS_DB_PATH": "/path/to/veritas/data/veritas.db"
      }
    }
  }
}
```

## Available tools

| Tool | Description |
|------|-------------|
| `get_state` | Current phase, position, equity, win rate |
| `list_assumptions` | All assumptions with reliability scores |
| `get_assumption` | Single assumption detail + Lean theorem ref |
| `get_recent_trades` | Recent trade history |
| `verify_theorem` | Lean theorem verification status |
| `would_take_signal` | Ask Veritas: would you take this trade? |

## Example queries to try

- "What's Veritas's current state?"
- "What assumptions has Veritas learned about?"
- "Has the funding_rate_reverts assumption been reliable?"
- "If I wanted to short BTC right now, what would Veritas say?"
- "Is the positionSize_capped theorem proven?"
- "Show me the last 5 trades Veritas made"
