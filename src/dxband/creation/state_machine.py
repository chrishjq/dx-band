# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from datetime import datetime

from dxband.models.creation_job import CreationJob, CreationJobState

ACTIVE_STATES = frozenset(
    {
        CreationJobState.VALIDATING_INPUT,
        CreationJobState.SEPARATING,
        CreationJobState.VALIDATING_STEMS,
        CreationJobState.IMPORTING_LRC,
        CreationJobState.IMPORTING_TEXT,
        CreationJobState.BUILDING_LYRICS_DRAFT,
        CreationJobState.AWAITING_LYRIC_REVIEW,
        CreationJobState.PACKAGING,
    }
)

ALLOWED_TRANSITIONS: dict[CreationJobState, frozenset[CreationJobState]] = {
    CreationJobState.IDLE: frozenset({CreationJobState.VALIDATING_INPUT}),
    CreationJobState.VALIDATING_INPUT: frozenset({CreationJobState.SEPARATING}),
    CreationJobState.SEPARATING: frozenset({CreationJobState.VALIDATING_STEMS}),
    CreationJobState.VALIDATING_STEMS: frozenset(
        {CreationJobState.IMPORTING_LRC, CreationJobState.IMPORTING_TEXT}
    ),
    CreationJobState.IMPORTING_LRC: frozenset({CreationJobState.BUILDING_LYRICS_DRAFT}),
    CreationJobState.IMPORTING_TEXT: frozenset({CreationJobState.BUILDING_LYRICS_DRAFT}),
    CreationJobState.BUILDING_LYRICS_DRAFT: frozenset({CreationJobState.AWAITING_LYRIC_REVIEW}),
    CreationJobState.AWAITING_LYRIC_REVIEW: frozenset({CreationJobState.PACKAGING}),
    CreationJobState.PACKAGING: frozenset({CreationJobState.COMPLETED}),
    CreationJobState.CANCELLING: frozenset({CreationJobState.CANCELLED}),
    CreationJobState.COMPLETED: frozenset(),
    CreationJobState.FAILED: frozenset(),
    CreationJobState.CANCELLED: frozenset(),
}


class InvalidStateTransitionError(ValueError):
    pass


class CreationStateMachine:
    def transition(self, job: CreationJob, new_state: CreationJobState) -> None:
        allowed = ALLOWED_TRANSITIONS[job.state]
        if new_state not in allowed:
            raise InvalidStateTransitionError(
                f"cannot transition creation job from {job.state.value} to {new_state.value}"
            )
        job.state = new_state
        job.updated_at = datetime.now().astimezone()

    def fail(self, job: CreationJob, message: str) -> None:
        if job.state in {
            CreationJobState.COMPLETED,
            CreationJobState.CANCELLED,
            CreationJobState.FAILED,
        }:
            raise InvalidStateTransitionError(f"cannot fail terminal job in {job.state.value}")
        job.state = CreationJobState.FAILED
        job.error_message = message
        job.updated_at = datetime.now().astimezone()

    def begin_cancellation(self, job: CreationJob) -> None:
        if job.state not in ACTIVE_STATES:
            raise InvalidStateTransitionError(f"cannot cancel job in {job.state.value}")
        job.state = CreationJobState.CANCELLING
        job.updated_at = datetime.now().astimezone()

    def finish_cancellation(self, job: CreationJob) -> None:
        self.transition(job, CreationJobState.CANCELLED)
