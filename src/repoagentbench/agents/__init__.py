from .base import Agent
from .claude_code import ClaudeCodeAgent
from .mock_fix import MockFixAgent


def get_agent(name: str) -> Agent:
    if name == "claude-code":
        return ClaudeCodeAgent()
    if name == "mock-fix":
        return MockFixAgent()
    raise ValueError(f"Unknown agent: {name}")
