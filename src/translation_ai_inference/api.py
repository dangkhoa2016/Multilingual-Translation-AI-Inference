"""FastAPI entrypoint. Read-only GETs never start GPU work."""
import secrets
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import make_engine, make_session_factory
from .dispatcher import dispatch_queued_runs, make_dispatcher
from .model_registry import MODEL_REGISTRY
from .repository import IdempotencyConflict, JobRepository, summarize_run_states
from .schemas import JobSubmitted, JobView, RunView, SubmitBenchmark, SubmitTranslation
from .settings import Settings

bearer = HTTPBearer(auto_error=False)


def create_api(settings: Settings | None = None, *, repository: JobRepository | None = None,
               dispatcher=None) -> FastAPI:
    settings = settings or Settings.from_environment()
    if repository is None:
        repository = JobRepository(make_session_factory(make_engine(settings.database_url)))
    dispatcher = dispatcher or make_dispatcher(settings.dispatcher_mode)
    api = FastAPI(title="Translation AI Inference — Modal + PostgreSQL", version="0.1.0",
                  description="P1/P2 mock-only foundation. No actual model inference is enabled.")

    def require_auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
        if not credentials or not secrets.compare_digest(
            credentials.credentials, settings.api_bearer_token
        ):
            raise HTTPException(status_code=401, detail="Invalid or missing bearer token",
                                headers={"WWW-Authenticate": "Bearer"})

    @api.get("/health")
    def health():
        # Deliberately no DB/GPU access.
        return {"status": "ok", "inference_enabled": False, "phase": "mock-only"}

    @api.get("/v1/models", dependencies=[Depends(require_auth)])
    def list_models():
        return {"models": [
            {"key": m.key, "checkpoint": m.checkpoint, "gguf_repository": m.gguf_repository,
             "quantization": m.quantization, "enabled": m.enabled,
             "runtime_verified": m.runtime_verified}
            for m in MODEL_REGISTRY.values()
        ]}

    def submit_job(kind: str, payload, model_keys: list[str], key: str | None) -> JobSubmitted:
        if key is not None and (not key.strip() or len(key) > 200):
            raise HTTPException(status_code=422, detail="Idempotency-Key must have 1–200 characters")
        try:
            job_id = repository.submit(
                owner=settings.request_owner, idempotency_key=key, kind=kind,
                payload=payload.model_dump(exclude={"model", "models"}), model_keys=model_keys,
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        # Dispatch only newly queued runs. Repeated HTTP requests with the same key cannot
        # dispatch the same run twice thanks to a compare-and-set claim operation.
        dispatch_queued_runs(repository, dispatcher, job_id, settings.request_owner)
        job = repository.get(job_id, settings.request_owner)
        return JobSubmitted(job_id=UUID(job_id), status=summarize_run_states(job.runs),
                            kind=kind, status_url=f"/v1/jobs/{job_id}")

    @api.post("/v1/jobs/translations", response_model=JobSubmitted,
              status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_auth)])
    def translations(payload: SubmitTranslation, idempotency_key: str | None = Header(default=None)):
        return submit_job("translation", payload, [payload.model], idempotency_key)

    @api.post("/v1/jobs/benchmarks", response_model=JobSubmitted,
              status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_auth)])
    def benchmarks(payload: SubmitBenchmark, idempotency_key: str | None = Header(default=None)):
        return submit_job("benchmark", payload, payload.models, idempotency_key)

    @api.get("/v1/jobs/{job_id}", response_model=JobView, dependencies=[Depends(require_auth)])
    def get_job(job_id: UUID):
        job = repository.get(str(job_id), settings.request_owner)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobView(
            job_id=job_id, kind=job.kind, status=summarize_run_states(job.runs),
            source_language=job.source_language, target_language=job.target_language,
            runs=[RunView(run_id=UUID(run.id), model=run.model_key, status=run.status,
                          translation_text=run.result.translation_text if run.result else None,
                          is_mock_result=run.result.is_mock_result if run.result else False,
                          error_code=run.error_code) for run in job.runs],
        )

    return api
