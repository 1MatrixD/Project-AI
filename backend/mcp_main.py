"""Точка входа MCP-сервера проекта (запускается Claude Code, см. .mcp.json плагина)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.mcp.server import main

if __name__ == "__main__":
    main()
