# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import shutil
import uuid
from datetime import datetime
from pathlib import Path

from dxband.models.creation_job import CreateSongRequest, CreationJob
from dxband.services.atomic_file_service import atomic_write_json
from dxband.services.hash_service import sha256_file


class CreationWorkspace:
    def __init__(self, library_root: Path) -> None:
        self.library_root = library_root.expanduser().resolve()
        self.work_root = self.library_root / ".work"

    def create(self, request: CreateSongRequest) -> CreationJob:
        now = datetime.now().astimezone()
        job_id = f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        workspace_dir = self.work_root / job_id
        workspace_dir.mkdir(parents=True, exist_ok=False)
        (workspace_dir / "logs").mkdir()
        (workspace_dir / "separated").mkdir()

        staged_source = workspace_dir / f"source{request.source_mp3.suffix.lower()}"
        shutil.copy2(request.source_mp3, staged_source)
        staged_lrc: Path | None = None
        if request.lrc_path is not None:
            staged_lrc = workspace_dir / "source.lrc"
            shutil.copy2(request.lrc_path, staged_lrc)

        staged_request = request.model_copy(
            update={"source_mp3": staged_source, "lrc_path": staged_lrc}
        )
        job = CreationJob(
            job_id=job_id,
            request=staged_request,
            workspace_dir=workspace_dir,
            created_at=now,
            updated_at=now,
            original_source_filename=request.source_mp3.name,
            original_source_sha256=sha256_file(request.source_mp3),
            original_lrc_filename=request.lrc_path.name if request.lrc_path else None,
            original_lrc_sha256=(
                sha256_file(request.lrc_path) if request.lrc_path is not None else None
            ),
        )
        self.save(job)
        return job

    @staticmethod
    def save(job: CreationJob) -> None:
        atomic_write_json(job.workspace_dir / "job.json", job)

    def cleanup(self, job: CreationJob) -> None:
        workspace = job.workspace_dir.resolve()
        work_root = self.work_root.resolve()
        if workspace.parent != work_root:
            raise ValueError("refusing to remove a directory outside the creation work root")
        shutil.rmtree(workspace, ignore_errors=False)


class JobLog:
    def __init__(self, workspace_dir: Path) -> None:
        self.path = workspace_dir / "logs" / "job.log"

    def write(self, message: str) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(f"{timestamp} {message.rstrip()}\n")
