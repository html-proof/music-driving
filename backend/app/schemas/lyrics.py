from pydantic import BaseModel, Field


class LyricLine(BaseModel):
    time_ms: int
    text: str


class Lyrics(BaseModel):
    song_id: str
    available: bool
    synced: bool = Field(description="True only when the source supplied real timestamps")
    instrumental: bool = False
    lines: list[LyricLine] = []
    plain_text: str | None = None
    source: str
    source_id: str | None = None
