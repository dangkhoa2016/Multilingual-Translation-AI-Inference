"""FastAPI entrypoint. Read-only GETs never start GPU work."""
import json
import secrets
import time
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from . import __version__
from .access_audit import AccessRecorder
from .auth_guard import AuthenticationFailureGuard, RequestRateGuard, client_identity
from .database import make_engine, make_session_factory, valid_token_count
from .dispatcher import dispatch_queued_runs, make_dispatcher
from .model_registry import MODEL_REGISTRY
from .quotas import QuotaExceeded
from .repository import IdempotencyConflict, JobRepository, RetryNotAllowed, summarize_run_states
from .schemas import JobSubmitted, JobView, RunView, SubmitBenchmark, SubmitTranslation
from .settings import Settings, _valid_api_bearer_token
from .telemetry import valid_metric


def create_api(settings: Settings | None = None, *, repository: JobRepository | None = None,
               dispatcher=None) -> FastAPI:
    settings = settings or Settings.from_environment()
    if repository is None:
        repository = JobRepository(make_session_factory(make_engine(settings.database_url)))
    dispatcher = dispatcher or make_dispatcher(settings.dispatcher_mode)
    api = FastAPI(
        title="Multilingual Translation AI Inference — Modal + PostgreSQL",
        version=__version__,
        description="PostgreSQL-backed async translation: model inference is mode-gated.",
        docs_url=None, redoc_url=None, openapi_url=None,
    )

    @api.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Do not echo submitted text or validator contexts. Escape invalid Unicode
        # even in untrusted field names, which may appear in error locations.
        # Unknown JSON keys can be user-controlled; never echo them in loc.
        # Preserve documented fields and small list indices for actionable errors.
        allowed_fields = {
            "body": frozenset({"source_language", "target_language", "text",
                               "options", "preserve_formatting", "model", "models"}),
            "path": frozenset({"job_id", "run_id"}),
        }
        details = []
        for item in error.errors():
            raw_location = item.get("loc", ())
            section = raw_location[0] if raw_location else None
            location = [
                part if (
                    isinstance(part, str)
                    and part in (allowed_fields if index == 0 else allowed_fields.get(section, ()))
                ) or (
                    section == "body" and type(part) is int and 0 <= part <= 4
                ) else "unknown_field"
                for index, part in enumerate(raw_location)
            ]
            details.append({
                "type": item["type"], "loc": location, "msg": item["msg"],
            })
        return Response(content=json.dumps({"detail": details}, ensure_ascii=True),
                        status_code=422, media_type="application/json")

    auth_guard = AuthenticationFailureGuard(
        max_failures=settings.auth_failure_limit,
        window_seconds=settings.auth_failure_window_seconds,
        lockout_seconds=settings.auth_lockout_seconds,
        max_clients=settings.auth_max_tracked_clients,
    )

    request_guard = RequestRateGuard(per_peer=settings.max_requests_per_minute_per_peer,
        per_process=settings.max_requests_per_minute_per_process, max_clients=settings.auth_max_tracked_clients)
    recorder = AccessRecorder(settings.max_requests_per_minute_per_process) if settings.audit_log_enabled else None

    def _authenticate_request(request: Request) -> None:
        if request.scope.get("_translation_bearer_verified"):
            return
        peer = client_identity(request)
        retry_after = request_guard.admit(peer)
        if retry_after is not None:
            raise HTTPException(status_code=429, detail="Request rate limit reached before authentication",
                headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"})
        authorization = request.headers.get("Authorization")
        prefix = "Bearer "
        # The scheme is case-insensitive; its 7 bytes do not count toward token length.
        credential = (
            authorization[len(prefix):]
            if authorization is not None and authorization[:len(prefix)].lower() == prefix.lower()
            else None
        )
        valid = (
            credential is not None
            and _valid_api_bearer_token(credential)
            and secrets.compare_digest(credential, settings.api_bearer_token)
        )
        if valid:
            auth_guard.clear_after_success(peer)
            request.scope["_translation_bearer_verified"] = True
            return
        retry_after = auth_guard.record_failure(peer)
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail="Too many failed authentication attempts",
                headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"},
            )
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )

    async def _guard_api_requests(request: Request, call_next):
        protected = request.url.path.startswith("/v1/")
        if protected:
            # Check authorization before parsing or buffering any request body.
            try:
                _authenticate_request(request)
            except HTTPException as error:
                return JSONResponse(
                    status_code=error.status_code,
                    content={"detail": error.detail},
                    headers={**error.headers, "X-Content-Type-Options": "nosniff"},
                )
            if request.method in {"POST", "PUT", "PATCH"}:
                raw_length = request.headers.get("Content-Length")
                if raw_length is not None:
                    try:
                        length = int(raw_length)
                        if length < 0:
                            raise ValueError
                    except ValueError:
                        return JSONResponse(
                            status_code=400, content={"detail": "Invalid Content-Length"},
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                        )
                    if length > settings.max_api_body_bytes:
                        return JSONResponse(
                            status_code=413, content={"detail": "Request body too large"},
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                        )
                # Content-Length can be omitted by a chunked HTTP client.
                chunks = []
                total = 0
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > settings.max_api_body_bytes:
                        return JSONResponse(
                            status_code=413, content={"detail": "Request body too large"},
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                        )
                    chunks.append(chunk)
                request._body = b"".join(chunks)

        response = await call_next(request)
        if protected:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @api.middleware("http")
    async def guard_api_requests(request: Request, call_next):
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)
        started = time.perf_counter()
        try:
            response = await _guard_api_requests(request, call_next)
        except Exception:
            # Driver exceptions may contain SQL values or private connection data.
            response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if recorder is not None:
            recorder.emit(method=request.method, path=request.url.path,
                status_code=response.status_code,
                authenticated=bool(request.scope.get("_translation_bearer_verified")),
                duration_ms=(time.perf_counter() - started) * 1000)
        return response

    def require_auth(request: Request) -> None:
        # Defense in depth: all /v1 endpoints also declare this dependency.
        _authenticate_request(request)

    @api.get("/health")
    def health():
        # Deliberately no DB/GPU access.
        real_inference = settings.dispatcher_mode == "modal-gpu"
        return {
            "status": "ok",
            "inference_enabled": real_inference,
            "phase": "gpu" if real_inference else "mock-only",
        }

    @api.get("/v1/models", dependencies=[Depends(require_auth)])
    def list_models():
        return {"models": [
            {"key": m.key, "checkpoint": m.checkpoint, "gguf_repository": m.gguf_repository,
             "quantization": m.quantization,
             "enabled": m.runtime_verified and settings.dispatcher_mode == "modal-gpu",
             "dispatch_enabled": settings.dispatcher_mode == "modal-gpu",
             "runtime_verified": m.runtime_verified,
             "runtime_status": "not_checked"}
            for m in MODEL_REGISTRY.values()
        ]}

    def submit_job(kind: str, payload, model_keys: list[str], key: str | None) -> JobSubmitted:
        if key is not None and (not key.strip() or len(key) > 200):
            raise HTTPException(status_code=422, detail="Idempotency-Key must have 1–200 characters")
        try:
            job_id = repository.submit(
                owner=settings.request_owner, idempotency_key=key, kind=kind,
                payload=payload.model_dump(exclude={"model", "models"}), model_keys=model_keys,
                max_jobs_per_minute=settings.max_jobs_per_minute,
                max_jobs_per_day=settings.max_jobs_per_day,
                max_model_runs_per_day=settings.max_model_runs_per_day,
                max_pending_jobs_per_owner=settings.max_pending_jobs_per_owner,
                max_pending_runs_per_model=settings.max_pending_runs_per_model,
                estimated_gpu_microusd_per_run=(
                    settings.estimated_gpu_microusd_per_run
                    if settings.dispatcher_mode == "modal-gpu" else 0
                ),
                max_estimated_gpu_microusd_per_day=(
                    settings.max_estimated_gpu_microusd_per_day
                    if settings.dispatcher_mode == "modal-gpu" else 0
                ),
            )
        except QuotaExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc),
                                headers={"Retry-After": str(exc.retry_after_seconds)}) from exc
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

    @api.post("/v1/jobs/{job_id}/runs/{run_id}/retry", response_model=JobSubmitted,
              status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_auth)])
    def retry_confirmed_failed_run(job_id: UUID, run_id: UUID):
        if repository.get(str(job_id), settings.request_owner) is None:
            raise HTTPException(status_code=404, detail="Job not found")
        try:
            repository.retry_failed_run(
                job_id=str(job_id), owner=settings.request_owner, run_id=str(run_id),
                max_attempts_per_model=settings.max_attempts_per_model,
                max_model_runs_per_day=settings.max_model_runs_per_day,
                max_pending_jobs_per_owner=settings.max_pending_jobs_per_owner,
                max_pending_runs_per_model=settings.max_pending_runs_per_model,
                estimated_gpu_microusd_per_run=(
                    settings.estimated_gpu_microusd_per_run
                    if settings.dispatcher_mode == "modal-gpu" else 0
                ),
                max_estimated_gpu_microusd_per_day=(
                    settings.max_estimated_gpu_microusd_per_day
                    if settings.dispatcher_mode == "modal-gpu" else 0
                ),
            )
        except QuotaExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc),
                                headers={"Retry-After": str(exc.retry_after_seconds)}) from exc
        except RetryNotAllowed as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        dispatch_queued_runs(repository, dispatcher, str(job_id), settings.request_owner)
        job = repository.get(str(job_id), settings.request_owner)
        return JobSubmitted(job_id=job_id, status=summarize_run_states(job.runs),
                            kind=job.kind, status_url=f"/v1/jobs/{job_id}")

    @api.get("/v1/jobs/{job_id}", response_model=JobView, dependencies=[Depends(require_auth)])
    def get_job(job_id: UUID):
        try:
            repository.consume_job_poll_quota(owner=settings.request_owner, limit=settings.max_job_polls_per_minute)
        except QuotaExceeded as exc:
            raise HTTPException(status_code=429, detail="Job polling limit reached",
                headers={"Retry-After": str(exc.retry_after_seconds)}) from None
        job = repository.get(str(job_id), settings.request_owner)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        def view(run):
            timings = {}
            # Attempt-created to worker-start includes scheduling and cold start.
            if run.created_at is not None and run.started_at is not None:
                timings["queue_ms"] = round(max(
                    0, (run.started_at - run.created_at).total_seconds() * 1000), 3)
            if run.created_at is not None and run.finished_at is not None:
                timings["total_ms"] = round(max(
                    0, (run.finished_at - run.created_at).total_seconds() * 1000), 3)
            try:
                metrics = json.loads(run.metrics_json) if run.metrics_json else {}
            except (ValueError, TypeError):
                metrics = {}
            if not isinstance(metrics, dict):
                metrics = {}
            raw_timings = metrics.get("timings")
            if isinstance(raw_timings, dict):
                for field in ("inference_ms", "prefill_ms", "decode_ms",
                              "prompt_per_second", "tokens_per_second"):
                    if (value := valid_metric(raw_timings.get(field))) is not None:
                        timings[field] = value
            resources = {}
            if isinstance(metrics.get("resources"), dict):
                for field in ("cpu_process_seconds", "cpu_utilization_percent",
                              "sampled_vram_mib", "sampled_gpu_utilization_percent"):
                    if (value := valid_metric(metrics["resources"].get(field))) is not None:
                        resources[field] = value
            usage = {}
            if run.result:
                if (count := valid_token_count(run.result.input_tokens)) is not None:
                    usage["prompt_tokens"] = count
                if (count := valid_token_count(run.result.output_tokens)) is not None:
                    usage["completion_tokens"] = count
                if len(usage) == 2:
                    usage["total_tokens"] = sum(usage.values())
            return RunView(
                run_id=UUID(run.id), model=run.model_key, attempt_no=run.attempt_no,
                status=run.status,
                translation_text=run.result.translation_text if run.result else None,
                is_mock_result=run.result.is_mock_result if run.result else False,
                error_code=run.error_code, usage=usage or None,
                timings=timings or None, resources=resources or None,
            )

        return JobView(
            job_id=job_id, kind=job.kind, status=summarize_run_states(job.runs),
            source_language=job.source_language, target_language=job.target_language,
            runs=[view(run) for run in job.runs],
        )

    return api
