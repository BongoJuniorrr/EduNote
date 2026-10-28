"""Validated, source-linked learning artifacts. No executable model-generated code."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourcedText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=6000)
    source_ids: list[str] = Field(min_length=1, max_length=12)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value):
        if not value.strip():
            raise ValueError("Sourced text cannot be blank")
        return value.strip()

    @field_validator("source_ids")
    @classmethod
    def unique_sources(cls, value):
        return list(dict.fromkeys(value))


class QuizItem(SourcedText):
    topic: str = Field(min_length=1, max_length=150)
    options: list[str] = Field(min_length=2, max_length=6)
    answer: int = Field(ge=0, le=5)
    explanation: str = Field(min_length=1, max_length=3000)

    @model_validator(mode="after")
    def valid_options(self):
        values = [value.strip() for value in self.options]
        if (
            self.answer >= len(values)
            or any(not value or "placeholder" in value.lower() for value in values)
            or len(set(values)) != len(values)
        ):
            raise ValueError("Quiz requires distinct nonempty options and a valid answer index")
        if not self.topic.strip() or not self.explanation.strip():
            raise ValueError("Quiz topic and explanation cannot be blank")
        self.options = values
        return self


class StudyPack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    goals: list[SourcedText] = Field(min_length=1, max_length=10)
    summary: list[SourcedText] = Field(min_length=1, max_length=12)
    concepts: list[SourcedText] = Field(min_length=1, max_length=20)
    quiz: list[QuizItem] = Field(min_length=1, max_length=20)
    rubric: list[SourcedText] = Field(min_length=1, max_length=10)

    def validate_sources(self, allowed: set[str]):
        for item in self.goals + self.summary + self.concepts + self.quiz + self.rubric:
            if not set(item.source_ids) <= allowed:
                raise ValueError("Artifact cites an unknown source; generation rejected")
        return self
