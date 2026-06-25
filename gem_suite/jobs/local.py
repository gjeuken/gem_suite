"""LocalProcessBackend: runs jobs in a process pool, artifacts on local disk.

Conforms to the JobBackend protocol. The same JobSpec drives SlurmBackend later
with no caller change — the only difference is where `execute_job` runs.
"""
from __future__ import annotations

import multiprocessing
import os
import tempfile
import time
from concurrent.futures import Future, ProcessPoolExecutor
from typing import Any

from gem_suite.jobs.runners import execute_job, read_result, result_suffix
from gem_suite.jobs.spec import JobSpec, JobState, JobStatus, JobType


class LocalProcessBackend:
    """JobBackend backed by a ProcessPoolExecutor and an in-memory status store."""

    def __init__(self, max_workers: int | None = None, result_dir: str | None = None) -> None:
        # 'spawn' (not fork): native solver libraries (Gurobi/GLPK) and the
        # multi-threaded parent are not fork-safe. A fresh interpreter per worker
        # is the portable, robust choice and mirrors how a SLURM node starts.
        self._pool = ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=multiprocessing.get_context("spawn"),
        )
        self._result_dir = result_dir or tempfile.mkdtemp(prefix="gem_jobs_")
        os.makedirs(self._result_dir, exist_ok=True)
        self._status: dict[str, JobStatus] = {}
        self._futures: dict[str, Future] = {}
        self._types: dict[str, JobType] = {}

    # -- submission --------------------------------------------------------- #

    def submit(self, spec: JobSpec) -> str:
        result_path = os.path.join(
            self._result_dir, f"{spec.job_id}{result_suffix(spec.job_type)}"
        )
        self._status[spec.job_id] = JobStatus(
            job_id=spec.job_id,
            state=JobState.PENDING,
            submitted_at=time.time(),
        )
        self._types[spec.job_id] = spec.job_type
        self._futures[spec.job_id] = self._pool.submit(execute_job, spec, result_path)
        return spec.job_id

    # -- polling ------------------------------------------------------------ #

    def _refresh(self, job_id: str) -> JobStatus:
        try:
            st = self._status[job_id]
        except KeyError:
            raise KeyError(f"Unknown job_id: {job_id!r}") from None
        fut = self._futures.get(job_id)
        if fut is None or st.state in (JobState.CANCELLED,):
            return st

        if fut.cancelled():
            st.state = JobState.CANCELLED
            st.finished_at = st.finished_at or time.time()
        elif fut.running():
            st.state = JobState.RUNNING
            st.started_at = st.started_at or time.time()
        elif fut.done():
            exc = fut.exception()
            st.finished_at = st.finished_at or time.time()
            if exc is not None:
                st.state = JobState.FAILED
                st.error = f"{type(exc).__name__}: {exc}"
            else:
                st.state = JobState.SUCCEEDED
                st.result_path = fut.result()
                st.progress = 1.0
        else:
            st.state = JobState.PENDING
        return st

    def status(self, job_id: str) -> JobStatus:
        return self._refresh(job_id)

    def list_jobs(self) -> list[JobStatus]:
        return [self._refresh(jid) for jid in self._status]

    # -- results / control -------------------------------------------------- #

    def result(self, job_id: str) -> Any:
        st = self._refresh(job_id)
        if st.state != JobState.SUCCEEDED:
            raise RuntimeError(
                f"Job {job_id} is {st.state.value}, not succeeded"
                + (f": {st.error}" if st.error else "")
            )
        return read_result(self._types[job_id], st.result_path)

    def cancel(self, job_id: str) -> bool:
        fut = self._futures.get(job_id)
        if fut is None:
            raise KeyError(f"Unknown job_id: {job_id!r}")
        cancelled = fut.cancel()   # only succeeds if not yet started
        if cancelled:
            st = self._status[job_id]
            st.state = JobState.CANCELLED
            st.finished_at = time.time()
        return cancelled

    # -- lifecycle ---------------------------------------------------------- #

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)

    def __enter__(self) -> "LocalProcessBackend":
        return self

    def __exit__(self, *exc) -> None:
        self.shutdown(wait=False)
