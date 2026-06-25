"""SlurmBackend: conforming stub (implemented in a later milestone).

This exists now only to prove the seam: it has the exact JobBackend surface as
LocalProcessBackend, so calling code is identical regardless of where jobs run.
When implemented it will submit `execute_job(spec, result_path)` as an sbatch
script writing to a shared filesystem, and poll via `squeue` / `sacct`. Because
runners are pure and reference the model by path, no runner code changes.
"""
from __future__ import annotations

from typing import Any

from gem_suite.jobs.spec import JobSpec, JobStatus


class SlurmBackend:
    """Conforming stub. Every method raises until the SLURM milestone."""

    def __init__(self, partition: str | None = None, result_dir: str | None = None) -> None:
        self.partition = partition
        self.result_dir = result_dir

    def submit(self, spec: JobSpec) -> str:
        raise NotImplementedError("SlurmBackend is a stub; use LocalProcessBackend")

    def status(self, job_id: str) -> JobStatus:
        raise NotImplementedError("SlurmBackend is a stub; use LocalProcessBackend")

    def result(self, job_id: str) -> Any:
        raise NotImplementedError("SlurmBackend is a stub; use LocalProcessBackend")

    def cancel(self, job_id: str) -> bool:
        raise NotImplementedError("SlurmBackend is a stub; use LocalProcessBackend")

    def list_jobs(self) -> list[JobStatus]:
        raise NotImplementedError("SlurmBackend is a stub; use LocalProcessBackend")
