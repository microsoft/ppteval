"""
GeminiAgent implementation using Google Gemini Computer Use API.

This agent uses Gemini 2.5 Computer Use Preview model with the computer_use tool
to interact with GUI environments. It handles:
- Normalized coordinates (0-999)
- 14 supported UI actions
- URL tracking in state
- Function call/response pattern
- Safety decision handling
"""

import logging
from typing import Any

from google import genai
from google.genai import types
from google.genai.types import Content, Part

from ppteval.action_spaces import GeminiActionSpace
from ppteval.config import GeminiConfig
from ppteval.core.base import Action, Agent, State

logger = logging.getLogger(__name__)


class GeminiAgent(Agent):
    """
    Gemini Computer Use agent implementation.

    Uses Gemini 2.5 Computer Use Preview model with computer_use tool.
    Coordinates are normalized to 0-999 grid regardless of screen size.
    """

    def __init__(
        self,
        config: GeminiConfig,
        excluded_actions: list[str] | None = None,
        **kwargs
    ):
        """
        Initialize Gemini agent.

        Args:
            config: Gemini configuration
            excluded_actions: Optional list of action names to exclude
            **kwargs: Additional arguments
        """
        self.config = config
        self.action_space = GeminiActionSpace()
        self.instruction = None
        self.contents: list[Content] = []
        self.current_url = None

        # Initialize Gemini client
        if config.api_key:
            self.client = genai.Client(api_key=config.api_key)
        else:
            self.client = genai.Client()  # Will use GOOGLE_API_KEY env var

        # Configure model with computer_use tool
        self.excluded_actions = excluded_actions or []
        self.generate_config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                        excluded_predefined_functions=self.excluded_actions
                    )
                )
            ],
            temperature=config.temperature,
            top_p=config.top_p,
            max_output_tokens=config.max_output_tokens,
        )

        # Model name - use Computer Use preview model
        self.model_name = "gemini-2.5-computer-use-preview-10-2025"

        logger.debug(
            f"Initialized GeminiAgent with model={self.model_name}, "
            f"excluded_actions={self.excluded_actions}"
        )

    def step(self, state: State) -> Action:
        """
        Execute one step of the agent.

        Args:
            state: Current state (screenshot + metadata)

        Returns:
            Action to execute
        """
        logger.debug(f"GeminiAgent.step() called with state type: {type(state).__name__}")

        # Extract URL from state if available
        if hasattr(state, 'metadata') and isinstance(state.metadata, dict):
            self.current_url = state.metadata.get('url', self.current_url)

        # Convert state to screenshot bytes
        screenshot_bytes = self.action_space.format_state(state)

        # First turn: Add instruction + screenshot
        if not self.contents:
            if not self.instruction:
                logger.warning("No instruction set for Gemini agent")
                self.instruction = "Perform the task shown in the screenshot."

            logger.debug(f"Starting new conversation with instruction: {self.instruction[:100]}...")
            self.contents = [
                Content(
                    role="user",
                    parts=[
                        Part(text=self.instruction),
                        Part.from_bytes(data=screenshot_bytes, mime_type='image/png')
                    ]
                )
            ]
        else:
            # Subsequent turns: Should be after function execution
            logger.debug("Continuing conversation with existing history")

        # Generate response
        logger.debug(f"Calling Gemini API with {len(self.contents)} content items")
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=self.contents,
            config=self.generate_config,
        )

        logger.debug(f"Received response from Gemini with {len(response.candidates)} candidates")

        # Get first candidate
        if not response.candidates:
            logger.error("No candidates in Gemini response")
            return Action(action_type="finish", params={"message": "No response from model"})

        candidate = response.candidates[0]

        # Add model response to history
        self.contents.append(candidate.content)

        # Parse response to action
        # The action space checks for function_call and extracts the action.
        action = self.action_space.parse_response(response)

        logger.debug(f"Parsed action: {action.action_type}")

        # If not a function call (i.e., text response), it's a finish action
        has_function_calls = any(
            part.function_call for part in candidate.content.parts
        )

        if not has_function_calls:
            logger.debug("No function calls found, treating as finish action")
            # Extract text response
            text_parts = [part.text for part in candidate.content.parts if part.text]
            message = " ".join(text_parts) if text_parts else "Task completed"
            return Action(action_type="finish", params={"message": message})

        return action

    def add_function_response(
        self,
        action: Action,
        screenshot_bytes: bytes,
        url: str | None = None
    ) -> None:
        """
        Add function response to conversation history.

        This should be called after executing an action to provide feedback to the model.

        Args:
            action: The action that was executed
            screenshot_bytes: Screenshot after action execution
            url: Current URL (if available)
        """
        if url:
            self.current_url = url

        # Build function response
        response_data = {"url": self.current_url or ""}

        # Create function response with screenshot
        function_response = types.FunctionResponse(
            name=action.action_type,  # Function name matches action type
            response=response_data,
            parts=[
                types.FunctionResponsePart(
                    inline_data=types.FunctionResponseBlob(
                        mime_type="image/png",
                        data=screenshot_bytes
                    )
                )
            ]
        )

        # Add to conversation history
        self.contents.append(
            Content(
                role="user",
                parts=[Part(function_response=function_response)]
            )
        )

        logger.debug(f"Added function response for action: {action.action_type}")

    def reset(self) -> None:
        """Reset agent state."""
        logger.debug("Resetting GeminiAgent conversation history")
        self.contents = []
        self.current_url = None

    def set_instruction(self, instruction: str) -> None:
        """
        Set the task instruction.

        Args:
            instruction: Task instruction to execute
        """
        logger.debug(f"Setting instruction: {instruction[:100]}...")
        self.instruction = instruction
        # Reset conversation when instruction changes
        self.reset()

    def close(self) -> None:
        """Cleanup resources."""
        logger.debug("Closing GeminiAgent (no resources to cleanup)")
        # Gemini client doesn't need explicit cleanup
        pass
