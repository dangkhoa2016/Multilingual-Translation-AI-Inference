"""Persistent, model-specific llama-server process inside an isolated Modal L40S class.

No public endpoints are opened: llama-server binds to 127.0.0.1 in the
container, while the authenticated CPU gateway dispatches via Modal RPC.
A GPU class's @modal.enter loads the verified GGUF once for warm reuse.
"""
import json
import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .database import valid_token_count
from .language import normalize_language_label, same_language
from .model_registry import MODEL_REGISTRY
from .text import validate_translation_text

MANIFEST_PATH = Path("/opt/four_l40s_workers_q8_0_manifest.json")
WEIGHTS = Path("/weights")
SERVER = "/opt/llama.cpp/build/bin/llama-server"
HTTP_BASE = "http://127.0.0.1:8093"
RUNTIME_PROBE_TIMEOUT = 240


class InferenceFailure(RuntimeError):
    """A model returned a definitively unusable result."""


class UnsupportedLanguagePair(InferenceFailure):
    """Model explicitly reported that it cannot translate the requested pair."""


class ExecutionUncertain(RuntimeError):
    """A request may have reached an engine but did not confirm a result."""


def load_verified_spec(model_key: str, manifest_path: Path = MANIFEST_PATH,
                       weight_root: Path = WEIGHTS) -> dict:
    """Require a CPU-written hash marker; never download files on GPU."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if model_key not in MODEL_REGISTRY:
        raise ValueError("Unknown model")
    spec = manifest["models"][model_key]
    marker_name = ("hy_mt2_q8_0_verified.json" if model_key == "hy_mt2_30b"
                   else "verified_gguf_q8_0.json")
    marker_file = weight_root / marker_name
    weight_file = weight_root / spec["gguf_filename"]
    if not marker_file.is_file() or not weight_file.is_file():
        raise RuntimeError("Verified model file or marker is missing")
    marker = json.loads(marker_file.read_text(encoding="utf-8"))
    if (marker.get("sha256_verified_locally") != spec["gguf_lfs_sha256"]
            or marker.get("repo_revision") != spec["gguf_revision"]
            or marker.get("bytes", spec["gguf_size_bytes"]) != spec["gguf_size_bytes"]
            or weight_file.stat().st_size != spec["gguf_size_bytes"]):
        raise RuntimeError("Model weight marker/revision/file size mismatch")
    return spec


def build_translation_request(model_key: str, source_language: str,
                              target_language: str, text: str,
                              options_json: str) -> dict:
    if model_key not in MODEL_REGISTRY:
        raise ValueError("Model not supported")
    source = normalize_language_label(source_language)
    target = normalize_language_label(target_language)
    if same_language(source, target):
        raise ValueError("Source and target languages must differ")
    if not text.strip() or len(text) > 1000:
        raise ValueError("Source text must have 1–1000 nonempty Unicode characters")
    validate_translation_text(text)
    options = json.loads(options_json)
    if not isinstance(options, dict) or set(options) != {"preserve_formatting"}:
        raise ValueError("Unexpected translation options")
    if not isinstance(options["preserve_formatting"], bool):
        raise ValueError("Invalid preserve_formatting")
    formatting = (
        "Keep paragraph breaks, identifiers and placeholders intact. "
        if options["preserve_formatting"] else ""
    )
    user = (
        f"Translate the following text from the language labeled "
        f"{json.dumps(source, ensure_ascii=False)} into the language labeled "
        f"{json.dumps(target, ensure_ascii=False)}. "
        f"Labels may be language names, ISO codes or BCP-47 tags. "
        f"{formatting}Only output the translated result, without "
        f"explanations or reasoning. If unable to translate that pair, "
        f"output exactly UNSUPPORTED_LANGUAGE_PAIR.\n\n{text}"
    )
    params = {
        "model": model_key,
        "messages": [{"role": "user", "content": user}],
        "max_tokens": 1536,
        "seed": 42,
        "stream": False,
    }
    decoding = {
        "hy_mt2_30b": {"temperature": 0.7, "top_p": 1.0, "top_k": -1},
        "index_35b": {"temperature": 0.0, "top_p": 1.0, "top_k": 20},
        "gemma4_31b_it": {"temperature": 1.0, "top_p": 0.95, "top_k": 64},
        "qwen35_35b": {"temperature": 0.7, "top_p": 0.8, "top_k": 20},
    }
    params.update(decoding[model_key])
    return params


def extract_translation(response: dict) -> tuple[str, int | None, int | None]:
    """Never persist a reasoning-only or truncated completion as a translation."""
    try:
        choice = response["choices"][0]
        content = choice["message"]["content"]
        reason = choice["finish_reason"]
    except (KeyError, TypeError, IndexError) as exc:
        raise InferenceFailure("Malformed completion schema") from exc
    if not isinstance(content, str) or not content.strip():
        raise InferenceFailure("Completion has no translated content")
    if reason == "length":
        raise InferenceFailure("Output truncated by token budget")
    if reason not in ("stop", "eos_token"):
        raise InferenceFailure("Unexpected completion finish reason")
    if content.strip() == "UNSUPPORTED_LANGUAGE_PAIR":
        raise UnsupportedLanguagePair("Model reported unsupported language pair")
    if "<think>" in content or "</think>" in content:
        raise InferenceFailure("Reasoning marker leaked into translation")
    usage = response.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = valid_token_count(usage.get("prompt_tokens"))
    output_tokens = valid_token_count(usage.get("completion_tokens"))
    # Preserve whitespace as produced by the model; trimming is only used
    # for detecting empty or unsupported-pair completions above.
    return content, input_tokens, output_tokens


def _request_json(endpoint: str, payload: dict | None = None, *,
                  timeout: int = 10) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        HTTP_BASE + endpoint, data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


class L40SModelRuntime:
    """Per-GPU-container lifecycle: start once, serve multiple queued runs, stop."""

    def __init__(self, model_key: str):
        self.model_key = model_key
        self.process: subprocess.Popen | None = None
        self.log_file = None
        self.spec = None
        self.ready_seconds = None
        self._thread_metrics = threading.local()

    def start(self) -> None:
        spec = load_verified_spec(self.model_key)
        self.spec = spec
        args = [
            SERVER, "--model", str(WEIGHTS / spec["gguf_filename"]),
            "--host", "127.0.0.1", "--port", "8093",
            "--ctx-size", "4096", "--n-gpu-layers", "99",
            "--batch-size", "256", "--ubatch-size", "128",
            "--parallel", "1", "--threads", "4",
            "--no-webui", "--jinja",
        ]
        if self.model_key in {"index_35b", "gemma4_31b_it", "qwen35_35b"}:
            args += ["--chat-template-kwargs", '{"enable_thinking":false}']
        self.log_file = open("/tmp/translation_l40s_model_server.log", "w", encoding="utf-8")
        start = time.monotonic()
        self.process = subprocess.Popen(
            args, stdout=self.log_file, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            deadline = start + RUNTIME_PROBE_TIMEOUT
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise InferenceFailure("Engine exited while loading model")
                try:
                    if _request_json("/health", timeout=3).get("status") == "ok":
                        self.ready_seconds = round(time.monotonic() - start, 3)
                        return
                except (OSError, ValueError, TimeoutError, urllib.error.URLError):
                    pass
                time.sleep(2)
            raise InferenceFailure("Engine did not become ready within its startup budget")
        except Exception:
            self.stop()
            raise

    def translate(self, source_language: str, target_language: str,
                  text: str, options_json: str) -> tuple[str, int | None, int | None]:
        if self.process is None or self.process.poll() is not None:
            raise InferenceFailure("Engine is not running")
        request = build_translation_request(
            self.model_key, source_language, target_language, text, options_json,
        )
        request["model"] = self.spec["gguf_filename"]
        self._thread_metrics.timings = {}
        try:
            output = _request_json("/v1/chat/completions", request, timeout=240)
        except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
            raise ExecutionUncertain("Completion status unknown") from exc
        translated = extract_translation(output)
        from .telemetry import llama_timing_metrics
        self._thread_metrics.timings = llama_timing_metrics(output)
        return translated

    def readiness(self) -> dict:
        """Authenticated internal Modal RPC; never a publicly exposed GPU URL."""
        if self.process is None or self.process.poll() is not None:
            raise InferenceFailure("GPU model server is not healthy")
        if _request_json("/health", timeout=5).get("status") != "ok":
            raise InferenceFailure("GPU model server health is not OK")
        row = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,uuid,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            text=True, timeout=10,
        ).strip().splitlines()
        if len(row) != 1:
            raise InferenceFailure("Expected exactly one NVIDIA GPU")
        parts = [x.strip() for x in row[0].split(",")]
        if len(parts) != 4 or "L40S" not in parts[0]:
            raise InferenceFailure("Unexpected NVIDIA GPU type")
        return {
            "model": self.model_key,
            "gpu": parts[0],
            "gpu_uuid": parts[1],
            "sampled_vram_mib": int(parts[2]),
            "total_vram_mib": int(parts[3]),
            "ready_seconds": self.ready_seconds,
            "verified_weight_file": self.spec["gguf_filename"],
            "single_GPU": True,
            "model_loaded": True,
        }

    def process_job(self, run_id: str, claim_token: str) -> bool:
        """DB claim fences duplicate attempts; terminal results are durable."""
        from .database import make_engine, make_session_factory
        from .repository import JobRepository

        database_url = os.environ["TRANSLATION_INFERENCE_DATABASE_URL"]
        engine = make_engine(database_url)
        try:
            repo = JobRepository(make_session_factory(engine))
            task = repo.start_run(run_id, claim_token)
            if task is None:
                return False
            source, target, text, options, model_key = task
            if model_key != self.model_key:
                repo.fail_run(run_id, claim_token, "GPU_MODEL_MISMATCH")
                return False
            from .telemetry import cpu_during_inference, process_cpu_seconds, sample_gpu, valid_metric
            self._thread_metrics.timings = {}
            cpu_before = process_cpu_seconds(self.process.pid if self.process else None)
            measured_start = time.perf_counter()
            try:
                translated, input_tokens, output_tokens = self.translate(
                    source, target, text, options,
                )
            except UnsupportedLanguagePair:
                repo.fail_run(run_id, claim_token, "UNSUPPORTED_LANGUAGE_PAIR")
                return False
            except InferenceFailure:
                repo.fail_run(run_id, claim_token, "GPU_INFERENCE_FAILED")
                return False
            except Exception:
                # Unknown execution outcome; no automatic retry and no double charge.
                repo.mark_execution_uncertain(run_id, claim_token, "GPU_EXECUTION_UNCERTAIN")
                return False
            elapsed = time.perf_counter() - measured_start
            timings = dict(getattr(self._thread_metrics, "timings", {}))
            if (inference_ms := valid_metric(elapsed * 1000)) is not None:
                timings["inference_ms"] = inference_ms
            cpu_after = process_cpu_seconds(self.process.pid if self.process else None)
            resources = cpu_during_inference(cpu_before, cpu_after, elapsed)
            resources.update(sample_gpu())
            return repo.finish_run(
                run_id, claim_token, translated, mock=False,
                input_tokens=input_tokens, output_tokens=output_tokens,
                metrics={"timings": timings, "resources": resources},
            )
        finally:
            engine.dispose()

    def stop(self) -> None:
        proc = self.process
        self.process = None
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=10)
        if self.log_file is not None:
            self.log_file.close()
            self.log_file = None
