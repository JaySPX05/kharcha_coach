"""Does Token Factory return tool_calls for Nemotron Super? Run: python scripts/check_tool_calling.py"""
import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E702
from llm.client import chat  # noqa: E402

tool = {"type": "function", "function": {"name": "spend_by", "description": "Total spend for a merchant and month",
        "parameters": {"type": "object", "properties": {"merchant": {"type": "string"}, "month": {"type": "string"}}}}}
msg = chat("super", [{"role": "user", "content": "How much did I spend on Swiggy in 2026-09?"}],
           tools=[tool], tool_choice="auto", max_tokens=400, purpose="tool-check")
print("tool_calls:", [(c.function.name, c.function.arguments) for c in (msg.tool_calls or [])])
print("content:", repr(msg.content))
print("RESULT:", "native tool calling works -> keep CHAT_MODE=tools" if msg.tool_calls
      else "no tool_calls -> set CHAT_MODE=plan in .env (or check content for <tool_call> tags)")
