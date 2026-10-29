"""Where she thinks: builds the prompt, asks DeepSeek, records what the reply says to keep.
Never depends on the channels package."""

from fish.brain.ask import ask_json
from fish.brain.consolidate import Consolidator, similarity
from fish.brain.home_command import home_command
from fish.brain.leisure import away, moment_line
from fish.brain.llm import LLM, DeepSeekLLM, FakeLLM
from fish.brain.parse import Reply, parse_reply
from fish.brain.prompt import PromptContext, build_chat_messages
from fish.brain.respond import Brain
from fish.brain.world import Browser

__all__ = ["LLM", "Brain", "Browser", "Consolidator", "DeepSeekLLM", "FakeLLM", "PromptContext", "Reply", "away",
           "ask_json", "build_chat_messages", "home_command", "moment_line", "parse_reply", "similarity"]
