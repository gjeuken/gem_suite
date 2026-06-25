"""Milestone-4 tests: runners, FVA-as-parquet, and LocalProcessBackend."""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict

import pytest

from gem_suite import ModelService
from gem_suite.jobs import (
    JobSpec,
    JobState,
    JobStatus,
    JobType,
    LocalProcessBackend,
    SlurmBackend,
    StrainDesignParams,
)
from gem_suite.jobs.runners import read_fva_parquet, run_fva, write_fva_parquet
from gem_suite.model_service import FVAResult

RXNS = ["PFK", "PGI", "PGK"]
FVA_PARAMS = {"reaction_list": RXNS, "fraction_of_optimum": 1.0,
              "loopless": False, "processes": 1}


@pytest.fixture
def fva_spec(model_path: str) -> JobSpec:
    return JobSpec(
        job_type=JobType.FVA,
        model_path=model_path,
        params=FVA_PARAMS,
        solver="glpk",
        label="fva-test",
    )


@pytest.fixture
def backend():
    be = LocalProcessBackend(max_workers=2)
    try:
        yield be
    finally:
        be.shutdown(wait=False)


def _wait(be, job_id, timeout=120) -> JobStatus:
    deadline = time.time() + timeout
    terminal = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
    while time.time() < deadline:
        st = be.status(job_id)
        if st.state in terminal:
            return st
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} did not finish in {timeout}s")


# -- runner + serde (no backend) ------------------------------------------- #

def test_run_fva_matches_model_service(fva_spec: JobSpec, service: ModelService,
                                       session: str):
    direct = service.fva(session, reaction_list=RXNS, processes=1)
    via_runner = run_fva(fva_spec)
    assert isinstance(via_runner, FVAResult)
    assert set(via_runner.ranges) == set(direct.ranges) == set(RXNS)
    for r in RXNS:
        assert math.isclose(via_runner.ranges[r][0], direct.ranges[r][0], abs_tol=1e-6)
        assert math.isclose(via_runner.ranges[r][1], direct.ranges[r][1], abs_tol=1e-6)


def test_fva_parquet_roundtrip(fva_spec: JobSpec, tmp_path):
    result = run_fva(fva_spec)
    path = str(tmp_path / "fva.parquet")
    assert write_fva_parquet(result, path) == path
    loaded = read_fva_parquet(path)
    assert loaded.status == result.status
    assert loaded.fraction_of_optimum == result.fraction_of_optimum
    assert loaded.loopless == result.loopless
    assert loaded.ranges == result.ranges


# -- LocalProcessBackend end-to-end ---------------------------------------- #

def test_submit_poll_result(backend, fva_spec: JobSpec, service: ModelService,
                            session: str):
    job_id = backend.submit(fva_spec)
    assert job_id == fva_spec.job_id
    st = _wait(backend, job_id)
    assert st.state == JobState.SUCCEEDED
    assert st.result_path and st.result_path.endswith(".parquet")
    assert st.progress == 1.0
    assert st.submitted_at > 0 and st.finished_at is not None

    result = backend.result(job_id)
    assert isinstance(result, FVAResult)
    direct = service.fva(session, reaction_list=RXNS, processes=1)
    assert set(result.ranges) == set(direct.ranges)


def test_failed_job_reports_error(backend):
    bad = JobSpec(job_type=JobType.FVA, model_path="/no/such/model.xml",
                  params=FVA_PARAMS, solver="glpk")
    job_id = backend.submit(bad)
    st = _wait(backend, job_id)
    assert st.state == JobState.FAILED
    assert st.error
    with pytest.raises(RuntimeError):
        backend.result(job_id)


def test_result_raises_before_success(backend, fva_spec: JobSpec):
    bad = JobSpec(job_type=JobType.FVA, model_path="/no/such/model.xml",
                  params=FVA_PARAMS, solver="glpk")
    job_id = backend.submit(bad)
    _wait(backend, job_id)
    with pytest.raises(RuntimeError):
        backend.result(job_id)


def test_list_jobs(backend, fva_spec: JobSpec):
    j1 = backend.submit(fva_spec)
    j2 = backend.submit(JobSpec(job_type=JobType.FVA, model_path=fva_spec.model_path,
                                params=FVA_PARAMS, solver="glpk"))
    ids = {s.job_id for s in backend.list_jobs()}
    assert {j1, j2} <= ids


def test_cancel_queued_job(fva_spec: JobSpec):
    # one worker: a job submitted behind a running one is still queued and
    # can be cancelled before it starts.
    be = LocalProcessBackend(max_workers=1)
    try:
        be.submit(fva_spec)                       # occupies the single worker
        queued = JobSpec(job_type=JobType.FVA, model_path=fva_spec.model_path,
                         params=FVA_PARAMS, solver="glpk")
        be.submit(queued)
        cancelled = be.cancel(queued.job_id)
        assert cancelled is True
        assert be.status(queued.job_id).state == JobState.CANCELLED
    finally:
        be.shutdown(wait=False)


def test_cancel_unknown_job_raises(backend):
    with pytest.raises(KeyError):
        backend.cancel("nope")


def test_status_unknown_job_raises(backend):
    with pytest.raises(KeyError):
        backend.status("nope")


# -- JSON round-trippability (the core invariant) -------------------------- #

def test_jobspec_json_roundtrippable(fva_spec: JobSpec):
    blob = json.dumps(asdict(fva_spec))
    data = json.loads(blob)
    assert data["job_type"] == "fva"          # str-enum serializes to its value
    assert data["model_path"] == fva_spec.model_path
    restored = JobSpec(**data)
    assert restored.job_id == fva_spec.job_id


def test_jobstatus_json_roundtrippable(backend, fva_spec: JobSpec):
    job_id = backend.submit(fva_spec)
    st = _wait(backend, job_id)
    blob = json.dumps(asdict(st))
    data = json.loads(blob)
    assert data["state"] == "succeeded"
    assert JobStatus(**data).job_id == job_id


def test_strain_design_params_json(model_path: str):
    params = StrainDesignParams(target_reaction="EX_succ_e", max_size=3).to_params()
    json.dumps(params)
    spec = JobSpec(job_type=JobType.STRAIN_DESIGN, model_path=model_path,
                   params=params, solver="glpk")
    json.dumps(asdict(spec))


# -- SLURM stub conforms but is not implemented ---------------------------- #

def test_slurm_backend_conforms_and_stubs(fva_spec: JobSpec):
    be = SlurmBackend()
    for call in (lambda: be.submit(fva_spec),
                 lambda: be.status("x"),
                 lambda: be.result("x"),
                 lambda: be.cancel("x"),
                 lambda: be.list_jobs()):
        with pytest.raises(NotImplementedError):
            call()
