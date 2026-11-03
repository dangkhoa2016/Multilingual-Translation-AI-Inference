"""One Modal App: authenticated CPU gateway, mock fallback, four real L40S classes.

GPU workers are deployed but scale to zero by default. Routing remains mock-only
until the API Secret explicitly chooses TRANSLATION_DISPATCHER_MODE=modal-gpu.
All weights are pre-verified in separate Volumes; GPU never downloads weights.
"""
import json
import os
from pathlib import Path

import modal

from multilingual_translation_ai_inference.resource_names import (
    MODAL_API_AUTH_SECRET_NAME,
    MODAL_APP_NAME,
    MODAL_CPU_GATEWAY_FUNCTION_NAME,
    MODAL_CPU_MOCK_WORKER_FUNCTION_NAME,
    MODAL_GPU_WEIGHT_VOLUME_NAMES,
    MODAL_POSTGRESQL_CONNECTION_SECRET_NAME,
)

modal_application = modal.App(MODAL_APP_NAME)
app = modal_application

# The entrypoint module is imported again inside both CPU and GPU containers.
# Bundle the manifest at its module-relative path in every image.
MODEL_MANIFEST = Path(__file__).resolve().parent / "models/four_l40s_workers_q8_0_manifest.json"
CONTAINER_MANIFEST_PATH = "/root/models/four_l40s_workers_q8_0_manifest.json"

api_dependencies = modal.Image.debian_slim(python_version="3.12").pip_install(
    "fastapi==0.128.2", "pydantic==2.13.5", "sqlalchemy==2.0.50",
    "psycopg[binary]>=3.2,<4", "uvicorn>=0.34,<1",
).add_local_file(MODEL_MANIFEST, CONTAINER_MANIFEST_PATH).add_local_python_source(
    "multilingual_translation_ai_inference"
)

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
    from multilingual_translation_ai_inference.api import create_api
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

    from multilingual_translation_ai_inference.database import make_engine, make_session_factory
    from multilingual_translation_ai_inference.repository import JobRepository
    from multilingual_translation_ai_inference.worker import process_mock_translation_run

    database_url = os.environ["TRANSLATION_INFERENCE_DATABASE_URL"]
    engine = make_engine(database_url)
    try:
        repository = JobRepository(make_session_factory(engine))
        return process_mock_translation_run(repository, run_id, claim_token)
    finally:
        engine.dispose()


def _operations_monitor_schedule():
    """Choose a deploy-time CPU-only schedule; default leaves it off."""
    setting = os.environ.get(
        "TRANSLATION_OPERATIONS_MONITOR_SCHEDULE", "off"
    ).strip().lower()
    if setting == "off":
        return None
    if setting == "hourly":
        return modal.Period(hours=1)
    raise ValueError(
        "TRANSLATION_OPERATIONS_MONITOR_SCHEDULE must be 'off' or 'hourly'"
    )


@modal_application.function(
    name="translation_inference_cpu_operations_safety_monitor",
    image=api_dependencies,
    secrets=[postgresql_connection_secret],
    cpu=0.125,
    memory=256,
    timeout=90,
    min_containers=0,
    buffer_containers=0,
    max_containers=1,
    schedule=_operations_monitor_schedule(),
)
def translation_inference_cpu_operations_safety_monitor() -> dict:
    """Optional CPU-only PostgreSQL aggregate check; never runs/retries GPU.

    When enabled at deployment, Modal schedules an hourly invocation.
    Alerts are written to Modal Logs and mark the CPU invocation failed.
    This function does not send email/webhooks, auto-repair, or retry GPU.
    """
    import json
    import os
    from datetime import datetime, timezone

    from multilingual_translation_ai_inference.database import make_engine, make_session_factory
    from multilingual_translation_ai_inference.operations import collect_operations_snapshot
    from multilingual_translation_ai_inference.repository import JobRepository

    engine = make_engine(os.environ["TRANSLATION_INFERENCE_DATABASE_URL"])
    try:
        snapshot = collect_operations_snapshot(JobRepository(make_session_factory(engine)))
    finally:
        engine.dispose()
    alerts = []
    states = snapshot["total_runs_by_state"]
    if states.get("dispatch_uncertain", 0) or states.get("execution_uncertain", 0):
        alerts.append("uncertain_runs_need_operator_review")
    if snapshot["stale_dispatching_count"] or snapshot["stale_running_count"]:
        alerts.append("stale_active_jobs")
    if snapshot["recent_error_codes"]:
        alerts.append("recent_inference_error_codes")
    payload = {
        "type": "translation_inference_operations_safety_monitor",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "alert" if alerts else "healthy",
        "alerts": alerts,
        "run_counts": snapshot["total_runs_by_state"],
        "stale_dispatching": snapshot["stale_dispatching_count"],
        "stale_running": snapshot["stale_running_count"],
        "recent_error_codes": snapshot["recent_error_codes"],
        "gpu_allocations": 0,
        "automatic_retries": 0,
    }
    print(json.dumps(payload, sort_keys=True), flush=True)
    if alerts:
        raise RuntimeError("CPU operations monitor detected: " + ", ".join(alerts))
    return payload


# The exact revision and model-loader hash previously passed four L40S CUDA smokes.
# Image source builds on CPU only; these classes allocate GPU on a method call.
_model_manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
CUDA_REVISION = _model_manifest["llama_cpp_revision_hy_mt2_proven"]
HY_V3_LOADER_SHA256 = _model_manifest["models"]["hy_mt2_30b"]["llama_cpp_architecture_source_sha256"]

gpu_image = (
    modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .apt_install(
        "git", "cmake", "build-essential", "libcurl4-openssl-dev",
        "libssl-dev", "ca-certificates", "curl", "ninja-build",
    )
    .run_commands(
        "git clone --filter=blob:none https://github.com/ggml-org/llama.cpp.git /opt/llama.cpp"
        + f" && cd /opt/llama.cpp && git checkout --detach {CUDA_REVISION}",
        f"echo '{HY_V3_LOADER_SHA256}  /opt/llama.cpp/src/models/hy-v3.cpp' | sha256sum -c -",
        "cmake -S /opt/llama.cpp -B /opt/llama.cpp/build -G Ninja "
        "-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89 -DGGML_NATIVE=OFF "
        "-DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_UI=OFF "
        "-DLLAMA_USE_PREBUILT_UI=OFF -DCMAKE_BUILD_TYPE=Release",
        "cmake -S /opt/llama.cpp -B /opt/llama.cpp/build "
        "-DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined "
        "&& cmake --build /opt/llama.cpp/build --target llama-server --parallel 2",
    )
    .pip_install("sqlalchemy==2.0.50", "psycopg[binary]>=3.2,<4")
    .add_local_file(MODEL_MANIFEST, "/opt/four_l40s_workers_q8_0_manifest.json")
    .add_local_file(MODEL_MANIFEST, CONTAINER_MANIFEST_PATH)
    .add_local_python_source("multilingual_translation_ai_inference")
)

gpu_worker_common = {
    "image": gpu_image,
    "gpu": "L40S",
    "secrets": [postgresql_connection_secret],
    "cpu": 4,
    "memory": 8192,
    "timeout": 900,
    "startup_timeout": 450,
    "min_containers": 0,
    "buffer_containers": 0,
    "max_containers": 1,
    "scaledown_window": 5,
}


@modal_application.cls(
    volumes={"/weights": modal.Volume.from_name(MODAL_GPU_WEIGHT_VOLUME_NAMES["hy_mt2_30b"])},
    **gpu_worker_common,
)
class HyMT2L40SWorker:
    @modal.enter()
    def enter(self):
        from multilingual_translation_ai_inference.gpu_runtime import L40SModelRuntime
        self.runtime = L40SModelRuntime("hy_mt2_30b")
        self.runtime.start()

    @modal.method()
    def process_job(self, run_id: str, claim_token: str) -> bool:
        return self.runtime.process_job(run_id, claim_token)

    @modal.method()
    def readiness(self) -> dict:
        return self.runtime.readiness()

    @modal.exit()
    def exit(self):
        self.runtime.stop()


@modal_application.cls(
    volumes={"/weights": modal.Volume.from_name(MODAL_GPU_WEIGHT_VOLUME_NAMES["index_35b"])},
    **gpu_worker_common,
)
class IndexTranslateL40SWorker:
    @modal.enter()
    def enter(self):
        from multilingual_translation_ai_inference.gpu_runtime import L40SModelRuntime
        self.runtime = L40SModelRuntime("index_35b")
        self.runtime.start()

    @modal.method()
    def process_job(self, run_id: str, claim_token: str) -> bool:
        return self.runtime.process_job(run_id, claim_token)

    @modal.method()
    def readiness(self) -> dict:
        return self.runtime.readiness()

    @modal.exit()
    def exit(self):
        self.runtime.stop()


@modal_application.cls(
    volumes={"/weights": modal.Volume.from_name(MODAL_GPU_WEIGHT_VOLUME_NAMES["gemma4_31b_it"])},
    **gpu_worker_common,
)
class Gemma4L40SWorker:
    @modal.enter()
    def enter(self):
        from multilingual_translation_ai_inference.gpu_runtime import L40SModelRuntime
        self.runtime = L40SModelRuntime("gemma4_31b_it")
        self.runtime.start()

    @modal.method()
    def process_job(self, run_id: str, claim_token: str) -> bool:
        return self.runtime.process_job(run_id, claim_token)

    @modal.method()
    def readiness(self) -> dict:
        return self.runtime.readiness()

    @modal.exit()
    def exit(self):
        self.runtime.stop()


@modal_application.cls(
    volumes={"/weights": modal.Volume.from_name(MODAL_GPU_WEIGHT_VOLUME_NAMES["qwen35_35b"])},
    **gpu_worker_common,
)
class Qwen35L40SWorker:
    @modal.enter()
    def enter(self):
        from multilingual_translation_ai_inference.gpu_runtime import L40SModelRuntime
        self.runtime = L40SModelRuntime("qwen35_35b")
        self.runtime.start()

    @modal.method()
    def process_job(self, run_id: str, claim_token: str) -> bool:
        return self.runtime.process_job(run_id, claim_token)

    @modal.method()
    def readiness(self) -> dict:
        return self.runtime.readiness()

    @modal.exit()
    def exit(self):
        self.runtime.stop()
