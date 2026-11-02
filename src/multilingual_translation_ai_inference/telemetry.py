"""Best-effort per-run telemetry; no credentials, logs, or GPU allocations."""
import math
import os
import subprocess


def valid_metric(value, *, maximum=1_000_000_000):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return round(value, 3) if math.isfinite(value) and 0 <= value <= maximum else None


def llama_timing_metrics(response: dict) -> dict:
    raw = response.get("timings")
    if not isinstance(raw, dict):
        return {}
    fields = {"prompt_ms": "prefill_ms", "predicted_ms": "decode_ms",
              "prompt_per_second": "prompt_per_second",
              "predicted_per_second": "tokens_per_second"}
    return {dst: value for src, dst in fields.items()
            if (value := valid_metric(raw.get(src))) is not None}


def process_cpu_seconds(pid: int | None) -> float | None:
    """Read llama.cpp process CPU seconds across all threads, not Python CPU."""
    if not pid or pid < 1:
        return None
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as handle:
            fields = handle.read().rsplit(") ", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return None


def sample_gpu() -> dict:
    """One post-request sample, NOT average, peak, or GPU inference duration."""
    try:
        raw = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
             "--format=csv,noheader,nounits"],
            text=True, timeout=3, stderr=subprocess.DEVNULL,
        ).strip().splitlines()
        if len(raw) != 1:
            return {}
        parts = [int(x.strip()) for x in raw[0].split(",")]
        if len(parts) != 2 or not (0 <= parts[0] <= 200000 and 0 <= parts[1] <= 100):
            return {}
        return {"sampled_vram_mib": parts[0], "sampled_gpu_utilization_percent": parts[1]}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def cpu_during_inference(before: float | None, after: float | None,
                         seconds: float) -> dict:
    if before is None or after is None or seconds <= 0 or after < before:
        return {}
    elapsed_cpu = valid_metric(after - before)
    # Multi-core CPU process utilization can exceed 100%.
    utilization = valid_metric(100 * (after - before) / seconds, maximum=100000)
    if elapsed_cpu is None or utilization is None:
        return {}
    return {"cpu_process_seconds": elapsed_cpu, "cpu_utilization_percent": utilization}
