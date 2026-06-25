"""Pure runners (spec -> result) and their result serialization.

Runners are backend-agnostic: they take a JobSpec, read the model from its
path, compute, and return a value type. `execute_job` wraps a runner with
artifact persistence and is the single unit of work both backends run — locally
in a worker process now, in a generated SLURM script later. Everything here is
module-level so it is picklable across a process boundary.
"""
from __future__ import annotations

import json
from dataclasses import asdict

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from gem_suite.model_service import FVAResult, compute_fva, read_model_file

from gem_suite.jobs.spec import JobSpec, JobType, StrainDesignParams

# Artifact extension per job type (FVA -> tabular parquet, strain design -> JSON).
_RESULT_SUFFIX = {JobType.FVA: ".parquet", JobType.STRAIN_DESIGN: ".json"}


def result_suffix(job_type: JobType) -> str:
    return _RESULT_SUFFIX.get(job_type, ".bin")


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #

def run_fva(spec: JobSpec) -> FVAResult:
    """Load the model referenced by `spec` and run FVA. Pure spec -> result."""
    model = read_model_file(spec.model_path)
    model.solver = spec.solver
    p = spec.params or {}
    return compute_fva(
        model,
        reaction_list=p.get("reaction_list"),
        fraction_of_optimum=p.get("fraction_of_optimum", 1.0),
        loopless=p.get("loopless", False),
        processes=p.get("processes"),
    )


def run_strain_design(spec: JobSpec):
    """Load the model referenced by `spec` and compute strain designs."""
    # imported here so the job layer loads without `straindesign` installed
    from gem_suite.strain_design import design_strains

    model = read_model_file(spec.model_path)
    params = StrainDesignParams(**spec.params)
    return design_strains(model, params, solver=spec.solver)


# --------------------------------------------------------------------------- #
# FVA result <-> parquet (scalars ride in the parquet schema metadata)
# --------------------------------------------------------------------------- #

def write_fva_parquet(result: FVAResult, path: str) -> str:
    df = pd.DataFrame(
        [
            {"reaction": rid, "minimum": lo, "maximum": hi}
            for rid, (lo, hi) in result.ranges.items()
        ],
        columns=["reaction", "minimum", "maximum"],
    )
    table = pa.Table.from_pandas(df, preserve_index=False)
    meta = dict(table.schema.metadata or {})
    meta.update(
        {
            b"status": result.status.encode(),
            b"fraction_of_optimum": repr(result.fraction_of_optimum).encode(),
            b"loopless": repr(result.loopless).encode(),
        }
    )
    pq.write_table(table.replace_schema_metadata(meta), path)
    return path


def read_fva_parquet(path: str) -> FVAResult:
    table = pq.read_table(path)
    meta = table.schema.metadata or {}
    df = table.to_pandas()
    ranges = {
        row.reaction: (float(row.minimum), float(row.maximum))
        for row in df.itertuples(index=False)
    }
    return FVAResult(
        status=meta.get(b"status", b"optimal").decode(),
        ranges=ranges,
        fraction_of_optimum=float(meta.get(b"fraction_of_optimum", b"1.0").decode()),
        loopless=meta.get(b"loopless", b"False").decode() == "True",
    )


# --------------------------------------------------------------------------- #
# Strain-design result <-> JSON (solution sets, not tabular)
# --------------------------------------------------------------------------- #

def write_strain_design_json(result, path: str) -> str:
    with open(path, "w") as fh:
        json.dump(asdict(result), fh)
    return path


def read_strain_design_json(path: str):
    from gem_suite.strain_design import StrainDesignResult, StrainDesignSolution

    with open(path) as fh:
        data = json.load(fh)
    return StrainDesignResult(
        status=data["status"],
        approach=data["approach"],
        gene_level=data["gene_level"],
        solutions=[StrainDesignSolution(**s) for s in data["solutions"]],
    )


# --------------------------------------------------------------------------- #
# Dispatch — one unit of work shared by every backend
# --------------------------------------------------------------------------- #

def execute_job(spec: JobSpec, result_path: str) -> str:
    """Run the spec's runner and persist its artifact at `result_path`.

    Returns `result_path`. Runs inside the worker (local) or the SLURM script.
    """
    if spec.job_type == JobType.FVA:
        return write_fva_parquet(run_fva(spec), result_path)
    if spec.job_type == JobType.STRAIN_DESIGN:
        return write_strain_design_json(run_strain_design(spec), result_path)
    raise ValueError(f"Unknown job_type: {spec.job_type!r}")


def read_result(job_type: JobType, result_path: str):
    """Load the artifact written by `execute_job` back into its value type."""
    if job_type == JobType.FVA:
        return read_fva_parquet(result_path)
    if job_type == JobType.STRAIN_DESIGN:
        return read_strain_design_json(result_path)
    raise ValueError(f"No result reader for job_type: {job_type!r}")
