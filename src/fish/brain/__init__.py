"""Where she thinks: builds the prompt, asks DeepSeek, records what the reply says to keep.
Never depends on the channels package."""

from fish.brain.consolidate import Consolidator
from fish.brain.llm import LLM, DeepSeekLLM, FakeLLM
from fish.brain.parse import Reply, parse_reply
from fish.brain.prompt import PromptContext, build_chat_messages
from fish.brain.respond import Brain

__all__ = ["LLM", "Brain", "Consolidator", "DeepSeekLLM", "FakeLLM", "PromptContext", "Reply",
           "build_chat_messages", "parse_reply"]
