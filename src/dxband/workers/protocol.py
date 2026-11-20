# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from typing import Annotated, Literal

from pydantic import Field, JsonValue, TypeAdapter

from dxband.models.base import StrictModel


class StageEvent(StrictModel):
    type: Literal["stage"] = "stage"
    value: str


class LogEvent(StrictModel):
    type: Literal["log"] = "log"
    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str


class ProgressEvent(StrictModel):
    type: Literal["progress"] = "progress"
    value: float = Field(ge=0.0, le=1.0)


class ResultEvent(StrictModel):
    type: Literal["result"] = "result"
    path: str
    data: dict[str, JsonValue] = Field(default_factory=dict)


class ErrorEvent(StrictModel):
    type: Literal["error"] = "error"
    message: str
    details: str | None = None


WorkerEvent = Annotated[
    StageEvent | LogEvent | ProgressEvent | ResultEvent | ErrorEvent,
    Field(discriminator="type"),
]
_EVENT_ADAPTER: TypeAdapter[WorkerEvent] = TypeAdapter(WorkerEvent)


def encode_event(event: WorkerEvent) -> str:
    return _EVENT_ADAPTER.dump_json(event).decode("utf-8")


def parse_event(line: str) -> WorkerEvent | None:
    try:
        return _EVENT_ADAPTER.validate_json(line, strict=True)
    except ValueError:
        return None
