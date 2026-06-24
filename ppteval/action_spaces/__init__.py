"""Agent-specific action spaces for ppteval."""

from ppteval.action_spaces.screenenv import BaseScreenEnvActionSpace
from ppteval.action_spaces.cua import CUAActionSpace
from ppteval.action_spaces.gpt5x import GPT5xActionSpace
from ppteval.action_spaces.claude import ClaudeActionSpace
from ppteval.action_spaces.uitars import UITARSActionSpace
from ppteval.action_spaces.gemini import GeminiActionSpace
from ppteval.action_spaces.qwen3vl import Qwen3VLActionSpace
from ppteval.action_spaces.opencua import OpenCUAActionSpace

__all__ = [
    "BaseScreenEnvActionSpace",
    "CUAActionSpace",
    "GPT5xActionSpace",
    "ClaudeActionSpace",
    "UITARSActionSpace",
    "GeminiActionSpace",
    "Qwen3VLActionSpace",
    "OpenCUAActionSpace",
]
