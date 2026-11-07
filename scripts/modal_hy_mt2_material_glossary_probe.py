"""Opt-in, one-L40S development probe for Hy-MT2 material/terminology fidelity.

With no flags, validate the local synthetic fixture only (no GPU):
    modal run --profile bsmith888 scripts/modal_hy_mt2_material_glossary_probe.py

For one explicitly bounded GPU diagnostic:
    modal run --profile bsmith888 scripts/modal_hy_mt2_material_glossary_probe.py --run
"""
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from scripts.modal_hy_mt2_gpu_smoke import BIN, REVISION, volume
from scripts.modal_hy_mt2_gpu_smoke import image as verified_cuda_image

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks/hy_mt2_material_glossary_probe_v1.json"
REPORT = ROOT / "reports/hy_mt2_material_glossary.json"
app = modal.App("translation-ai-inference-hy-mt2-material-glossary-probe")
image = (verified_cuda_image.add_local_file(DATASET, "/opt/vi_material_glossary_probe.json")
         .add_local_python_source("scripts"))
LANGS = {"en": "English", "de": "German", "ja": "Japanese", "ko": "Korean"}
PROMPTS = ("baseline_official_v1", "material_glossary_v1")
TIME_BUDGET = 500
TOKEN_BUDGET = 9_000

# Cheap lexical evidence only: occurrence does not prove correct negation or semantics.
LEXICAL = {
    "en": {"silver": ["silver"], "copper": ["copper"], "gold": ["gold"]},
    "de": {"silver": ["silber"], "copper": ["kupfer"], "gold": ["gold"]},
    "ja": {"silver": ["銀"], "copper": ["銅"], "gold": ["金", "黄金"]},
    "ko": {"silver": ["은", "실버"], "copper": ["구리", "동"], "gold": ["금", "골드"]},
}


def load_fixture(path=DATASET):
    raw = Path(path).read_bytes()
    suite = json.loads(raw)
    assert suite["kind"] == "synthetic_material_glossary_diagnostic_unreferenced"
    assert suite["prompt_variants"] == list(PROMPTS)
    assert len(suite["cases"]) == 20
    seen = set()
    for item in suite["cases"]:
        assert item["id"] not in seen
        seen.add(item["id"])
        assert item["target_language"] in LANGS
        assert item["source_language"] == "vi"
        assert 1 <= len(item["source_text"]) <= 1000
        assert item["group"] in ("development_retest", "independent_probe")
        assert all(c in ("silver", "copper", "gold") for c in item["material_concepts_to_inspect"])
    return suite, hashlib.sha256(raw).hexdigest()


def build_prompt(case, variant):
    if variant not in PROMPTS:
        raise ValueError("Unknown frozen prompt variant")
    first = (
        f"Translate the following text into {LANGS[case['target_language']]}. "
        "Note that you should only output the translated result without "
        "any additional explanation:\n\n"
    )
    if variant == "baseline_official_v1":
        return first + case["source_text"]
    glossary = (
        "Translation terminology instruction (not part of the source): "
        "When material is meant literally, Vietnamese 'bạc' means silver, "
        "'đồng' means copper and 'vàng' means gold. "
        "Do not substitute one material for another. "
        "Preserve negation, numeric identifiers and personal names. "
        "Preserve Lâm as written in Latin-script target languages.\n\n"
    )
    return first + glossary + case["source_text"]


def lexical_material_hint(output, language, concept):
    """Material-word signals, never a semantic or negation correctness score."""
    import re

    patterns = {
        "ja": {
            "silver": r"(?:銀製|銀の|銀で|銀色|純銀|シルバー)",
            "copper": r"(?:銅製|銅の|銅で|純銅|銅や|銅を)",
            "gold": r"(?:金製|金の|金で|黄金|純金|金色)",
        },
        "ko": {
            "silver": r"(?:실버|순은|은제|은색|은빛|은으로|은\s+(?:반지|열쇠|나침반|상자|소재|금속))",
            "copper": r"(?:구리|동제|동으로|동\s+(?:상자|금속|소재))",
            "gold": r"(?:순금|황금|골드|금제|금으로|금색|금빛|금\s+(?:왕관|반지|상자))",
        },
    }
    if language in patterns:
        return bool(re.search(patterns[language][concept], output))
    return any(form.lower() in output.lower() for form in LEXICAL[language][concept])


def analyze_output(case, result, variant):
    import re

    dest = case["target_language"]
    found = {
        concept: lexical_material_hint(result, dest, concept)
        for concept in case["material_concepts_to_inspect"]
    }
    literals = re.findall(r"(?:SKU-[A-Z0-9-]+|INV-\d+|LOT-\d+)", case["source_text"])
    missing = [s for s in literals if s not in result]
    return {
        "lexical_concepts_present": found,
        "missing_literal_identifiers": missing,
        "latin_name_lam_preserved": (
            "Lâm" in result if dest in ("en", "de") and "Lâm" in case["source_text"]
            else None
        ),
        "human_review_required": True,
        "variant": variant,
    }


@app.function(
    image=image,
    gpu="L40S",
    volumes={"/weights": volume},
    cpu=4,
    memory=8192,
    timeout=650,
    min_containers=0,
    buffer_containers=0,
    max_containers=1,
    scaledown_window=5,
)
def run_probe(max_cases: int) -> dict:
    import os
    import signal
    import subprocess
    import urllib.error
    import urllib.request

    suite = json.loads(Path("/opt/vi_material_glossary_probe.json").read_text(encoding="utf-8"))
    assert 1 <= max_cases <= 20
    lock = json.loads(Path("/opt/hy_mt2_lock.json").read_text(encoding="utf-8"))
    gguf = lock["gguf"]
    path = Path("/weights") / gguf["file"]
    marker = json.loads(Path("/weights/hy_mt2_q8_0_verified.json").read_text(encoding="utf-8"))
    if (not path.is_file() or path.stat().st_size != gguf["size_bytes"]
            or marker.get("repo_revision") != gguf["revision"]
            or marker.get("sha256_verified_locally") != gguf["sha256_from_huggingface_metadata"]):
        raise RuntimeError("Hy-MT2 pinned Volume missing or verification marker does not match")
    t0 = time.monotonic()
    logs = open("/tmp/hy_mt2_glossary_probe.log", "w", encoding="utf-8")
    process = subprocess.Popen(
        [BIN, "--model", str(path), "--host", "127.0.0.1", "--port", "8080",
         "--ctx-size", "4096", "--n-gpu-layers", "99", "--batch-size", "256",
         "--ubatch-size", "128", "--parallel", "1", "--threads", "4",
         "--no-webui", "--jinja"],
        stdout=logs, stderr=subprocess.STDOUT, start_new_session=True,
    )

    def ask(endpoint, body=None, timeout=5):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            "http://127.0.0.1:8080" + endpoint, data=raw,
            headers={"Content-Type": "application/json"} if raw else {},
            method="POST" if raw else "GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)

    records = []
    consumed = 0
    memory_high = 0
    server_ready = None
    stop_reason = None
    try:
        while time.monotonic() - t0 < 160:
            if process.poll() is not None:
                raise RuntimeError("llama-server terminated before ready")
            try:
                if ask("/health", timeout=3).get("status") == "ok":
                    server_ready = round(time.monotonic() - t0, 3)
                    break
            except (OSError, ValueError, TimeoutError, urllib.error.URLError):
                pass
            time.sleep(1)
        if server_ready is None:
            raise TimeoutError("Model server startup exceeded 160 seconds")
        for ix, case in enumerate(suite["cases"][:max_cases]):
            # Alternate order to reduce warm-cache/order bias between prompt variants.
            ordered_variants = PROMPTS if ix % 2 == 0 else tuple(reversed(PROMPTS))
            for variant in ordered_variants:
                if time.monotonic() - t0 + 95 >= TIME_BUDGET:
                    stop_reason = "gpu_runtime_budget"
                    break
                if consumed + 100 >= TOKEN_BUDGET:
                    stop_reason = "token_budget"
                    break
                cap = min(1024 if case["group"] == "development_retest" else 300,
                          TOKEN_BUDGET - consumed)
                record = {
                    "id": case["id"],
                    "group": case["group"],
                    "direction": "vi->" + case["target_language"],
                    "variant": variant,
                    "source_text": case["source_text"],
                    "input_characters": len(case["source_text"]),
                }
                t = time.monotonic()
                try:
                    response = ask("/v1/chat/completions", {
                        "model": gguf["file"],
                        "messages": [{"role": "user", "content": build_prompt(case, variant)}],
                        "temperature": 0.7, "top_p": 1.0, "top_k": -1,
                        "repeat_penalty": 1.0, "seed": 42,
                        "max_tokens": cap, "stream": False,
                    }, timeout=90)
                    output = response["choices"][0]["message"]["content"]
                    if not isinstance(output, str) or not output:
                        raise ValueError("No translation returned")
                    usage = response.get("usage", {})
                    tokens = int(usage.get("completion_tokens") or 0)
                    consumed += tokens
                    record.update({
                        "output": output,
                        "elapsed_seconds": round(time.monotonic() - t, 3),
                        "completion_tokens": tokens,
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "finish_reason": response["choices"][0].get("finish_reason"),
                        "analysis": analyze_output(case, output, variant),
                        "error": None,
                    })
                except Exception as e:
                    record.update({
                        "output": None,
                        "elapsed_seconds": round(time.monotonic() - t, 3),
                        "error": type(e).__name__,
                        "analysis": None,
                    })
                records.append(record)
                print("Probe", case["id"], variant, record["elapsed_seconds"],
                      "error", record["error"], flush=True)
                try:
                    value = subprocess.check_output(
                        ["nvidia-smi", "--query-gpu=memory.used",
                         "--format=csv,noheader,nounits"], text=True, timeout=5)
                    memory_high = max(memory_high, int(value.strip().splitlines()[0]))
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
            if stop_reason:
                break
        return {
            "status": "completed" if len(records) == max_cases * len(PROMPTS) else "partial",
            "records": records,
            "requested_cases": max_cases,
            "model_ready_seconds": server_ready,
            "function_seconds": round(time.monotonic() - t0, 3),
            "max_observed_gpu_memory_mib": memory_high,
            "gpu_peak_is_exact": False,
            "completion_tokens_total": consumed,
            "stop_reason": stop_reason,
            "gguf_sha256": marker["sha256_verified_locally"],
            "llama_cpp_revision": REVISION,
            "engine_settings": {"context_size": 4096, "gpu_layers": 99,
                                "seed": 42, "temperature": 0.7},
            "cost_controls": {"max_containers": 1, "function_timeout": 650,
                              "internal_seconds_budget": TIME_BUDGET,
                              "completion_tokens_budget": TOKEN_BUDGET},
        }
    finally:
        try:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
        logs.close()


@app.local_entrypoint()
def main(run: bool = False, max_cases: int = 20):
    suite, digest = load_fixture()
    if not 1 <= max_cases <= 20:
        raise ValueError("max_cases must be 1..20")
    print("Validated:", len(suite["cases"]), "cases x 2 prompts; SHA256", digest)
    print("Selected:", max_cases, "cases x 2, one L40S maximum, output token budget", TOKEN_BUDGET)
    if not run:
        print("CPU-only validation done; no GPU launched. Explicit --run required.")
        return
    start = time.monotonic()
    result = run_probe.remote(max_cases)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATASET.relative_to(ROOT)),
        "dataset_sha256": digest,
        "scope": "synthetic development diagnosis only, NOT a human quality benchmark",
        "modal_client_call_wall_seconds": round(time.monotonic() - start, 3),
        "result": result,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with REPORT.with_suffix(".csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "id", "group", "direction", "variant", "elapsed_seconds",
            "prompt_tokens", "completion_tokens", "finish_reason", "error",
            "lexical_concepts_present", "latin_name_lam_preserved",
        ], lineterminator="\n")
        writer.writeheader()
        for item in result["records"]:
            analysis = item.get("analysis") or {}
            writer.writerow({**{k: item.get(k) for k in writer.fieldnames},
                             "lexical_concepts_present": json.dumps(
                                 analysis.get("lexical_concepts_present", {}), ensure_ascii=False),
                             "latin_name_lam_preserved": analysis.get("latin_name_lam_preserved")})
    print("Saved result:", REPORT)
    print("Summary:", json.dumps({
        "status": result["status"], "requests": len(result["records"]),
        "gpu_seconds": result["function_seconds"],
        "rpc_wall_seconds": report["modal_client_call_wall_seconds"],
        "max_sampled_gpu_mib": result["max_observed_gpu_memory_mib"],
        "stop_reason": result["stop_reason"],
    }))
