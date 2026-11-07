"""Modal P1 deployment: CPU gateway + CPU mock worker, ZERO GPU usage.

We do not register L40S workers or mount/create volumes until P3 verification.
Deploy only after creating the two explicitly named Modal Secrets and the PostgreSQL schema.
"""
import modal

from translation_ai_inference.resource_names import (
    MODAL_API_AUTH_SECRET_NAME,
    MODAL_APP_NAME,
    MODAL_CPU_GATEWAY_FUNCTION_NAME,
    MODAL_CPU_MOCK_WORKER_FUNCTION_NAME,
    MODAL_POSTGRESQL_CONNECTION_SECRET_NAME,
)

modal_application = modal.App(MODAL_APP_NAME)

api_dependencies = modal.Image.debian_slim(python_version="3.12").pip_install(
    "fastapi==0.128.2", "pydantic==2.13.5", "sqlalchemy==2.0.50",
    "psycopg[binary]>=3.2,<4", "uvicorn>=0.34,<1",
).add_local_python_source("translation_ai_inference")

postgresql_connection_secret = modal.Secret.from_name(MODAL_POSTGRESQL_CONNECTION_SECRET_NAME)
auth_secret = modal.Secret.from_name(MODAL_API_AUTH_SECRET_NAME)


@modal_application.function(
    name=MODAL_CPU_GATEWAY_FUNCTION_NAME,
    image=api_dependencies,
    secrets=[postgresql_connection_secret, auth_secret],
    cpu=1.0,
    memory=512,
    min_containers=0,
    buffer_containers=0,
    max_containers=2,
    scaledown_window=60,
    timeout=120,
)
@modal.asgi_app()
def translation_inference_fastapi_cpu_gateway():
    from translation_ai_inference.api import create_api
    return create_api()


@modal_application.function(
    name=MODAL_CPU_MOCK_WORKER_FUNCTION_NAME,
    image=api_dependencies,
    secrets=[postgresql_connection_secret],
    cpu=0.5,
    memory=512,
    min_containers=0,
    buffer_containers=0,
    max_containers=2,
    scaledown_window=60,
    timeout=120,
)
def translation_inference_cpu_mock_job_worker(run_id: str, claim_token: str) -> bool:
    import os

    from translation_ai_inference.database import make_engine, make_session_factory
    from translation_ai_inference.repository import JobRepository
    from translation_ai_inference.worker import process_mock_translation_run

    database_url = os.environ["TRANSLATION_INFERENCE_DATABASE_URL"]
    repository = JobRepository(make_session_factory(make_engine(database_url)))
    return process_mock_translation_run(repository, run_id, claim_token)
