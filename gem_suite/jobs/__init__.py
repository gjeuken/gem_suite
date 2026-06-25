"""Job layer: detachable heavy compute (FVA, strain design).

See SPEC.md. The caller talks only to a JobBackend; runners are pure functions
and specs reference the model by path, so the same code runs locally or on SLURM.
"""
from __future__ import annotations

from gem_suite.jobs.local import LocalProcessBackend
from gem_suite.jobs.runners import (
    execute_job,
    read_result,
    run_fva,
    run_strain_design,
)
from gem_suite.jobs.slurm import SlurmBackend
from gem_suite.jobs.spec import (
    JobBackend,
    JobSpec,
    JobState,
    JobStatus,
    JobType,
    StrainDesignParams,
)

__all__ = [
    "JobBackend",
    "JobSpec",
    "JobState",
    "JobStatus",
    "JobType",
    "StrainDesignParams",
    "LocalProcessBackend",
    "SlurmBackend",
    "run_fva",
    "run_strain_design",
    "execute_job",
    "read_result",
]
