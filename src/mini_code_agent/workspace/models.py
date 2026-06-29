from pydantic import BaseModel, ConfigDict, Field


class WorkspaceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_file_bytes: int = Field(default=1024 * 1024, ge=1, le=16 * 1024 * 1024)
    max_path_chars: int = Field(default=1024, ge=1, le=1024)


class SearchLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_files: int = Field(default=10_000, ge=1, le=100_000)
    max_total_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        le=256 * 1024 * 1024,
    )
    max_results: int = Field(default=200, ge=1, le=10_000)
    max_depth: int = Field(default=32, ge=1, le=64)
    max_line_chars: int = Field(default=20_000, ge=1, le=100_000)
    max_preview_chars: int = Field(default=500, ge=1, le=2_000)
