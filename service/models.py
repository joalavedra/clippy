"""Pydantic models exposed by the service API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Platform = Literal["youtube", "local", "tiktok", "instagram", "gdrive"]
Layout = Literal["single", "podcast"]
Ratio = Literal["9:16", "16:9", "1:1"]
AssetState = Literal["not_planned", "planned", "ready", "posted"]


class ProjectCreate(BaseModel):
    name: str
    platform: Platform
    url: str | None = None
    local_path: str | None = None
    layout: Layout = "single"

    @model_validator(mode="after")
    def exactly_one_source(self):
        if bool(self.url) == bool(self.local_path):
            raise ValueError("exactly one of url or local_path is required")
        return self


class Project(ProjectCreate):
    id: str
    created_at: str


class FormatSpec(BaseModel):
    ratio: Ratio
    min: float = Field(gt=0)
    max: float = Field(gt=0)

    @model_validator(mode="after")
    def min_before_max(self):
        if self.min >= self.max:
            raise ValueError("min must be less than max")
        return self


class JobOptions(BaseModel):
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    story_style: Literal["styled"] = "styled"
    gemini_timeout: int = Field(default=180, gt=0)
    project_name: str | None = None


class JobCreate(BaseModel):
    project_ids: list[str] = Field(min_length=1)
    brief: str
    formats: list[FormatSpec] = Field(min_length=1)
    clips: int = Field(default=2, ge=1, le=10)
    options: JobOptions = Field(default_factory=JobOptions)

    @model_validator(mode="after")
    def unique_format_ratios(self):
        ratios = [item.ratio for item in self.formats]
        if len(ratios) != len(set(ratios)):
            raise ValueError("formats must not contain duplicate ratios")
        return self


class Job(BaseModel):
    id: str
    brief: str
    formats: list[FormatSpec]
    clips: int
    options: JobOptions
    project_ids: list[str]
    status: Literal["queued", "running", "done", "failed"]
    stage: str
    percent: float
    error: str | None = None
    created_at: str
    updated_at: str


class JobEvent(BaseModel):
    id: str
    job_id: str
    ts: str
    stage: str
    message: str


class Render(BaseModel):
    id: str
    asset_id: str
    ratio: str
    duration: float
    file_key: str
    thumb_key: str | None = None
    recipe_clip: dict
    url: str


class Asset(BaseModel):
    id: str
    job_id: str
    project_ids: list[str]
    clip_id: int
    title: str
    hook_line: str
    rationale: str
    viral_score: int
    hashtags: list[str]
    metadata: dict
    state: AssetState
    favorite: bool
    created_at: str
    renders: list[Render] = []

    model_config = ConfigDict(from_attributes=True)


class AssetPatch(BaseModel):
    state: AssetState | None = None
    favorite: bool | None = None
