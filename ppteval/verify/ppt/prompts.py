from rubric.utils.llm_tools import generate_prompt_descriptions_for_functions, llm_call, vlm_call

from ..prompts import RUBRIC_GEN_PROMPT_CONTEXT_TEMPLATE

PYTHON_CONTEXT = '''
@dataclass
class AnimationEffect:
    """Represents a single animation effect"""

    slide_id: str
    element_id: str
    effect_type: str
    trigger: str
    delay: float
    duration: float
    order: int
    # Note, element_text may sometimes be a superset of the finer grained text actually animated.
    element_text: Optional[str] = None
    element_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        ...


@dataclass
class SlideTransition:
    """Represents a slide transition"""

    slide_id: str
    transition_type: str
    duration: float
    direction: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        ...


@dataclass
class Slide:
    """Represents a slide with its metadata"""

    slide_id: str
    slide_number: int
    title: Optional[str] = None
    layout_type: Optional[str] = None
    element_count: int = 0
    notes: Optional[str] = None
    content_hash: Optional[str] = None


    def to_dict(self) -> Dict[str, Any]:
        ...

@dataclass
class PowerPointDiff:
    """Container for PowerPoint differences"""

    added_animations: List[AnimationEffect]
    removed_animations: List[AnimationEffect]
    modified_animations: List[Tuple[AnimationEffect, AnimationEffect]]
    added_transitions: List[SlideTransition]
    removed_transitions: List[SlideTransition]
    modified_transitions: List[Tuple[SlideTransition, SlideTransition]]
    added_slides: List[Slide]
    removed_slides: List[Slide]
    modified_slides: List[Tuple[Slide, Slide]]

    def to_dict(self) -> Dict[str, Any]:
        ...

@dataclass
class SlideScreenshot:
    """Represents a slide screenshot"""
    slide_number: int
    image_path: str
    slide_id: Optional[str] = None

'''

GLOBAL_VARIABLES = """ppt_diff: PowerPointDiff
original_ppt_screenshots: List[SlideScreenshot]
modified_ppt_screenshots: List[SlideScreenshot]
original_ppt_path: str
modified_ppt_path: str
"""

RUBRIC_GEN_PROMPT_CONTEXT = RUBRIC_GEN_PROMPT_CONTEXT_TEMPLATE.format(
    app_name="Microsoft PowerPoint",
    python_context=PYTHON_CONTEXT,
    available_packages="python-pptx",
    global_variables=GLOBAL_VARIABLES,
    available_functions="\n\n".join(
        generate_prompt_descriptions_for_functions(
            [
                llm_call,
                vlm_call,
            ]
        )
    ),
)

RUBRIC_GEN_GENERATION_GUIDELINES = """ADDITIONAL GUIDELINES:
1. Avoid using llm/vlm calls when possible as they are slow and expensive.
   Prefer direct python verification when possible.
   E.g., If checking for diffs across all or many slides in a presentation (e.g., when making sure that no extraneous changes were made),
   making model calls can be very slow and expensive.
   Though, vlm calls are likely useful when checking for colors, object positioning,
   slide layouts and evaluating aesthetics for the main change you are evaluating.
   Similarly, llm calls are helpful when semantically evaluating the text content of slides.
2. The PPTDiff object is provided to you since python-pptx does not natively provide
   animation/transition info. When things are possible using python-pptx, you can use that instead.
   But note that PPTDiff, only complements python-pptx with data about properties like animations/transitions/slide notes.
   Do not rely on it for other slide content and properties.
3. Do not unnecessarily complicate the rubric tree. Keep it simple and concise.
"""
