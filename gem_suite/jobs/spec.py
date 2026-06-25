"""Job specs and the backend protocol.

A JobSpec is fully JSON-serializable and references the model by FILE PATH,
never by in-memory handle. That single rule lets an identical spec run in a
local worker process now and as a SLURM submission later with no change to the
caller: a cobra.Model cannot cross to another process/node, a path can.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol
import uuid


class JobType(str, Enum):
    FVA = "fva"
    STRAIN_DESIGN = "strain_design"
    # FBA / pFBA are deliberately NOT jobs: they are fast and run synchronously
    # on ModelService.


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StrainDesignParams:
    """Maps onto the StrainDesign package (Schneider/Klamt, on COBRApy).

    Computes the gene/reaction knock-OUT and knock-IN sets required to couple a
    target to growth or to enforce a yield. Knock-ins are supplied via a
    candidate database of addable reactions (`ki_database`).
    """
    target_reaction: str
    approach: str = "MCS"                 # "MCS" | "OptKnock" | "RobustKnock" | "OptCouple"
    ko_candidates: list[str] | None = None    # reactions/genes allowed to be removed
    ki_candidates: list[str] | None = None    # reactions allowed to be added (knock-in)
    ki_database: str | None = None            # path to universal / KEGG-derived SBML
    gene_level: bool = True                   # gene KOs vs reaction KOs
    max_solutions: int = 1
    max_size: int | None = None               # cut-set size cap; None = unbounded (explodes)
    min_growth: float | None = None
    min_yield: float | None = None
    time_limit_s: int | None = None

    def to_params(self) -> dict[str, Any]:
        """Flatten into JobSpec.params (JSON-serializable)."""
        return self.__dict__.copy()


@dataclass
class JobSpec:
    job_type: JobType
    model_path: str                  # MUST be resolvable on the worker (shared FS for SLURM)
    params: dict[str, Any]           # type-specific
    solver: str = "gurobi"
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    label: str | None = None

    # params shape:
    #   FVA            -> {reaction_list, fraction_of_optimum, loopless, processes}
    #   STRAIN_DESIGN  -> StrainDesignParams.to_params()


@dataclass
class JobStatus:
    job_id: str
    state: JobState
    progress: float = 0.0            # 0..1 where the backend can report it
    message: str = ""
    submitted_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    result_path: str | None = None   # JSON / parquet artifact when SUCCEEDED
    error: str | None = None


class JobBackend(Protocol):
    """The only surface the caller (ModelService / GUI) talks to.

    Implemented twice with identical semantics: LocalProcessBackend (now),
    SlurmBackend (later).
    """

    def submit(self, spec: JobSpec) -> str:
        """Enqueue and return spec.job_id."""
        ...

    def status(self, job_id: str) -> JobStatus:
        ...

    def result(self, job_id: str) -> Any:
        """Load and return the artifact at status.result_path. Raises if not SUCCEEDED."""
        ...

    def cancel(self, job_id: str) -> bool:
        """Best-effort cancellation. Returns whether it took effect."""
        ...

    def list_jobs(self) -> list[JobStatus]:
        ...
