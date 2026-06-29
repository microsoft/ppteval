"""
PowerPoint grader using rubric-based verification.
"""

from pathlib import Path

from rubric import RubricTree

from ppteval.core.base import Grader, EvaluationResult


class PPTGrader(Grader):
    """PowerPoint grader using rubric-based verification"""

    def __init__(self, rubric_path: Path | str, conversion_mode: str = "online"):
        """
        Initialize grader with rubric.

        Args:
            rubric_path: Path to rubric file (JSON or YAML)
            conversion_mode: How to render slide screenshots for VLM scoring.
                ``"online"`` uses PowerPoint Online via OneDrive (requires
                Playwright Chromium). ``"com"`` uses local PowerPoint COM
                automation on Windows. Other modes: ``"libreoffice+poppler"``,
                ``"libreoffice+ghostscript"``.
        """
        self.rubric_path = Path(rubric_path)
        if not self.rubric_path.exists():
            raise FileNotFoundError(f"Rubric file not found: {self.rubric_path}")

        self.conversion_mode = conversion_mode

        # Load rubric tree
        self.rubric_tree = RubricTree.load_from_file(str(self.rubric_path))

    def evaluate(self, artifacts: dict[str, Path]) -> EvaluationResult:
        """
        Evaluate task completion using PPTVerifier.

        Args:
            artifacts: Dictionary containing:
                - "file": Path to modified PowerPoint file
                - "images": Path to zip of slide images (optional)
                - "original_file": Path to original PowerPoint file

        Returns:
            EvaluationResult with score and details
        """
        from ppteval.verify.ppt.verifier import PPTVerifier

        # Extract paths
        original_file = artifacts.get("original_file")
        modified_file = artifacts.get("file")

        if not original_file or not modified_file:
            return EvaluationResult(
                score=0.0,
                success=False,
                reason="Missing required files for verification",
                details={"artifacts": list(artifacts.keys())}
            )

        # Create verifier with rubric
        verifier = PPTVerifier(str(self.rubric_path))

        # Run verification
        try:
            score, reason = verifier.verify(
                original_file_path=str(original_file),
                modified_file_path=str(modified_file),
                include_reason=True,
                compute_strategy="default",
                non_critical_weight=0.3,
                conversion_mode=self.conversion_mode,
                use_cached_original_images=True,
            )

            # Update our rubric_tree with the scored version from the verifier
            self.rubric_tree = verifier.rubric_tree

            success = score == 1.0  # Consider success if score == 1.0

            return EvaluationResult(
                score=score,
                success=success,
                reason=reason,
                details={"rubric_path": str(self.rubric_path)}
            )
        except Exception as e:
            return EvaluationResult(
                score=0.0,
                success=False,
                reason=f"Verification error: {str(e)}",
                details={"error": str(e), "type": type(e).__name__}
            )

    def save_scored_rubric(self, output_path: str | Path) -> None:
        """
        Save the scored rubric to a JSON file.

        Args:
            output_path: Path to save the scored rubric
        """
        self.rubric_tree.save_as_file(str(output_path))
