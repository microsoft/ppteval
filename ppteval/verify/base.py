"""
Base verifier classes for Office application verifiers.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from rubric import RubricTree


class BaseVerifier(ABC):
    """
    Abstract base class for Office application verifiers.

    This class defines the common interface and structure that all verifiers
    should implement for evaluating changes in Office documents.
    """

    def __init__(self, rubric_path: str | Path):
        """
        Initialize the verifier with a rubric file.

        Args:
            rubric_path: Path to the rubric file or directory containing the rubric
        """
        self.rubric_tree = RubricTree.load_from_file(rubric_path)

    @abstractmethod
    def verify(
        self,
        original_file_path: str,
        modified_file_path: str,
        include_reason: bool = False,
        compute_strategy: Literal["default", "mind2web2"] = "default",
        non_critical_weight: float = 0.3,
    ) -> tuple[float, str]:
        """
        Verify that the modified file meets the requirements defined in the rubric.

        Args:
            original_file_path: Path to the original file
            modified_file_path: Path to the modified file
            include_reason: Whether to include reasoning in the output
            compute_strategy: Strategy for computing scores
            non_critical_weight: Weight for non-critical criteria

        Returns:
            Tuple of (score, reason) where score is a float between 0 and 1,
            and reason is a string explanation of the score
        """
        pass
