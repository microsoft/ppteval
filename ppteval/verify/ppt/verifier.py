from pathlib import Path
from typing import Literal

from rubric import RubricTree, RubricTreeGenerator
from rubric.utils.llm_tools import llm_call, vlm_call

from ..base import BaseVerifier
from .diff import PowerPointDiffEvaluator
from .prompts import RUBRIC_GEN_GENERATION_GUIDELINES, RUBRIC_GEN_PROMPT_CONTEXT
from PIL import Image


class ScreenshotsUnavailableError(RuntimeError):
    """Raised when a visual rubric requires slide screenshots but none can be
    produced (e.g. PowerPoint conversion service was unavailable). This signals
    the orchestrator to mark the task for verification-only retry rather than
    scoring it as a model failure.
    """

def generate_rubric_for_task(
    task: str,
    save_path: str | Path | None = None,
    temperature: float = 0.7,
    max_tokens: int = 10000,
    enforce_structured_output: bool = True,
    reasoning_effort: str | None = None,
    scorer_types: list[str] = ["function"],
    compute_strategy: Literal["default", "mind2web2"] = "default",
    critical_node_weight: float = 0.7,
) -> RubricTree:
    generator = RubricTreeGenerator()
    tree = generator.generate_rubric_tree(
        task=task,
        rubric_gen_prompt_context=RUBRIC_GEN_PROMPT_CONTEXT,
        rubric_gen_generation_guidelines=RUBRIC_GEN_GENERATION_GUIDELINES,
        temperature=temperature,
        max_tokens=max_tokens,
        scorer_types=scorer_types,
        enforce_structured_output=enforce_structured_output,
        reasoning_effort=reasoning_effort,
        compute_strategy=compute_strategy,
        critical_node_weight=critical_node_weight,
    )
    if save_path:
        tree.save_to_file(save_path)
    return tree


class PPTVerifier(BaseVerifier):
    """
    PowerPoint-specific verifier for evaluating changes in PowerPoint presentations.

    This verifier uses PowerPoint-specific diff evaluation and screenshot generation
    to assess whether modifications meet the requirements defined in the rubric.
    """

    def _requires_visual_evaluation(self) -> bool:
        """Check if any rubric nodes require visual evaluation."""
        nodes = self.rubric_tree.get_all_nodes()
        for node in nodes:
            if node.scorer and node.scorer._function_code and "vlm_call" in node.scorer._function_code:
                return True
        return False

    def verify(
        self,
        original_file_path: str,
        modified_file_path: str,
        include_reason: bool = False,
        compute_strategy: Literal["default", "mind2web2"] = "default",
        non_critical_weight: float = 0.3,
        conversion_mode: Literal["online", "com", "libreoffice+poppler", "libreoffice+ghostscript"] = "online",
        use_cached_original_images: bool = True
    ) -> tuple[float, str]:
        """
        Verify that the modified PowerPoint file meets the requirements.

        Args:
            original_file_path: Path to the original PowerPoint file
            modified_file_path: Path to the modified PowerPoint file
            include_reason: Whether to include reasoning in the output
            compute_strategy: Strategy for computing scores
            non_critical_weight: Weight for non-critical criteria

        Returns:
            Tuple of (score, reason) where score is a float between 0 and 1,
            and reason is a string explanation of the score
        """
        diff_evaluator = PowerPointDiffEvaluator()

        # Check if any of the rubric nodes require visual evaluation by checking if the scoring function contains "vlm_call"

        requires_visual = self._requires_visual_evaluation()
        if requires_visual:
            resolution = None
            original_zip_path = Path(original_file_path).with_suffix(".zip")
            if use_cached_original_images and original_zip_path.exists():
                original_ppt_screenshots = diff_evaluator.load_slide_screenshots(
                    original_zip_path, output_dir=None, pptx_path=original_file_path
                )
                if original_ppt_screenshots:
                    with Image.open(original_ppt_screenshots[0].image_path) as img:
                        resolution = img.size
            else:
                original_ppt_screenshots = diff_evaluator.generate_slide_screenshots(
                    original_file_path, conversion_mode=conversion_mode, resolution=resolution
                )

            if Path(modified_file_path).with_suffix(".zip").exists():
                modified_ppt_screenshots = diff_evaluator.load_slide_screenshots(
                    Path(modified_file_path).with_suffix(".zip"), output_dir=None, pptx_path=modified_file_path
                )
            else:
                print("No cached screenshots for modified file, generating new ones...")
                modified_ppt_screenshots = diff_evaluator.generate_slide_screenshots(
                    modified_file_path, conversion_mode=conversion_mode, resolution=resolution
                )

            # If a visual rubric required screenshots but none could be produced,
            # this is an infrastructure problem (rendering service flaked), not a
            # model failure. Try one fresh regeneration pass for any empty side
            # (cached zips may be empty/corrupt), then flag for verify-only retry.
            if not original_ppt_screenshots:
                print("Original screenshots empty; attempting fresh regeneration...")
                try:
                    original_ppt_screenshots = diff_evaluator.generate_slide_screenshots(
                        original_file_path, conversion_mode=conversion_mode, resolution=resolution
                    )
                except Exception as e:
                    print(f"Original screenshot regeneration failed: {e}")
            if not modified_ppt_screenshots:
                print("Modified screenshots empty; attempting fresh regeneration...")
                try:
                    modified_ppt_screenshots = diff_evaluator.generate_slide_screenshots(
                        modified_file_path, conversion_mode=conversion_mode, resolution=resolution
                    )
                except Exception as e:
                    print(f"Modified screenshot regeneration failed: {e}")

            if not original_ppt_screenshots or not modified_ppt_screenshots:
                raise ScreenshotsUnavailableError(
                    "Visual rubric requires slide screenshots, but generation/load "
                    f"produced none (original={len(original_ppt_screenshots)} slides, "
                    f"modified={len(modified_ppt_screenshots)} slides). "
                    "Flagging for verification-only retry."
                )
        else:
            original_ppt_screenshots = []
            modified_ppt_screenshots = []

        global_context = {
            "ppt_diff": diff_evaluator.compare_files(
                original_file_path, modified_file_path
            ),
            "original_ppt_screenshots": original_ppt_screenshots,
            "modified_ppt_screenshots": modified_ppt_screenshots,
            "original_ppt_path": original_file_path,
            "modified_ppt_path": modified_file_path,
            "llm_call": llm_call,
            "vlm_call": vlm_call,
        }

        try:
            return self.rubric_tree.evaluate(
                **global_context,
                include_reason=include_reason,
                compute_strategy=compute_strategy,
                non_critical_weight=non_critical_weight,
            )
        except ValueError as e:
            # The rubric library wraps any leaf-scorer exception as
            # ``ValueError("Function scoring failed: ...")`` (with ``__cause__``
            # set to the original). If the underlying cause was a
            # ScreenshotsUnavailableError, re-raise it so the orchestrator's
            # infra-retry path picks it up rather than logging a scoring failure.
            cause = e.__cause__
            if isinstance(cause, ScreenshotsUnavailableError):
                raise cause
            raise
