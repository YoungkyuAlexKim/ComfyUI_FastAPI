"""Provider-neutral request contracts shared by web/API and MCP adapters.

These models describe user intent instead of exposing internal workflow IDs.
Authentication and principal resolution deliberately live outside request bodies.
"""

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


AspectRatio = Literal["auto", "square", "landscape", "portrait"]
ImageQuality = Literal["low", "medium", "high"]


class ControlledRequest(BaseModel):
    """Controls shared by requests that may create billable work."""

    idempotency_key: str = Field(min_length=8, max_length=128)
    cost_confirmed: bool = False


class CreateImageRequest(ControlledRequest):
    capability: Literal["create_image"] = "create_image"
    operation: Literal["generate", "edit"] = "generate"
    prompt: str = Field(min_length=1, max_length=8_000)
    reference_image_ids: list[str] = Field(default_factory=list, max_length=14)
    aspect_ratio: AspectRatio = "auto"
    image_size: Optional[Literal["1K", "2K"]] = None
    image_model: Optional[str] = None
    image_quality: Optional[ImageQuality] = None

    @model_validator(mode="after")
    def editing_requires_an_image(self):
        if self.operation == "edit" and not self.reference_image_ids:
            raise ValueError("reference_image_ids is required for image editing")
        return self


class CreateCharacterSheetRequest(ControlledRequest):
    capability: Literal["create_character_sheet"] = "create_character_sheet"
    sheet_type: Literal["turnaround", "expressions"]
    reference_image_id: str = Field(min_length=1)
    prompt: str = Field(default="", max_length=4_000)
    count: Optional[int] = None
    image_size: Optional[Literal["1K", "2K"]] = None
    image_model: Optional[str] = None
    image_quality: Optional[ImageQuality] = None

    @model_validator(mode="after")
    def count_matches_sheet_type(self):
        allowed = {"turnaround": {3, 5, 8}, "expressions": {4, 9}}
        if self.count is not None and self.count not in allowed[self.sheet_type]:
            values = sorted(allowed[self.sheet_type])
            raise ValueError(f"count for {self.sheet_type} must be one of {values}")
        return self


class CreateStoryboardRequest(ControlledRequest):
    capability: Literal["create_storyboard"] = "create_storyboard"
    prompt: str = Field(min_length=1, max_length=8_000)
    reference_image_id: str = Field(min_length=1)
    cuts: Literal[6, 9] = 9
    image_size: Optional[Literal["1K", "2K"]] = None
    image_model: Optional[str] = None
    image_quality: Optional[ImageQuality] = None


class CreateGameUiAssetsRequest(ControlledRequest):
    capability: Literal["create_game_ui_assets"] = "create_game_ui_assets"
    prompt: str = Field(min_length=1, max_length=8_000)
    reference_image_ids: list[str] = Field(default_factory=list, max_length=3)
    grid: Literal["2x2"] = "2x2"
    background_mode: Literal["transparent", "opaque"] = "transparent"
    image_size: Literal["2K"] = "2K"
    image_quality: ImageQuality = "medium"


class RemoveBackgroundRequest(ControlledRequest):
    capability: Literal["remove_background"] = "remove_background"
    image_id: str = Field(min_length=1)
    method: Literal["auto", "chroma", "rmbg"] = "auto"
    chroma_color: Optional[str] = None
    mask_blur: int = Field(default=0, ge=0, le=64)
    mask_offset: int = Field(default=0, ge=-64, le=64)


class SeparateLayersRequest(ControlledRequest):
    capability: Literal["separate_layers"] = "separate_layers"
    image_id: str = Field(min_length=1)
    resolution: int = Field(default=1472, ge=768, le=1472, multiple_of=64)


class GenerateMusicRequest(ControlledRequest):
    capability: Literal["generate_music"] = "generate_music"
    prompt: str = Field(min_length=1, max_length=8_000)
    lyrics: str = Field(default="", max_length=20_000)
    bpm: Optional[int] = Field(default=None, ge=30, le=300)
    duration: Optional[int] = Field(default=None, ge=5, le=600)
    steps: Optional[int] = Field(default=None, ge=1, le=200)
    keyscale: Optional[str] = None
    timesignature: Optional[str] = None
    language: Optional[str] = None


CapabilityRequest = Annotated[
    Union[
        CreateImageRequest,
        CreateCharacterSheetRequest,
        CreateStoryboardRequest,
        CreateGameUiAssetsRequest,
        RemoveBackgroundRequest,
        SeparateLayersRequest,
        GenerateMusicRequest,
    ],
    Field(discriminator="capability"),
]


MCP_CAPABILITY_REQUEST_MODELS = {
    "create_image": CreateImageRequest,
    "create_character_sheet": CreateCharacterSheetRequest,
    "create_storyboard": CreateStoryboardRequest,
    "create_game_ui_assets": CreateGameUiAssetsRequest,
    "remove_background": RemoveBackgroundRequest,
    "separate_layers": SeparateLayersRequest,
    "generate_music": GenerateMusicRequest,
}
