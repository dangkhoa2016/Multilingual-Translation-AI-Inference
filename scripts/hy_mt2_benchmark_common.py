"""CPU-only validation and reporting helpers for Hy-MT2 diagnostic suite."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks/hy_mt2_diagnostic_v1.json"
PAIRS = {
    ("en", "vi"), ("vi", "en"), ("de", "vi"), ("vi", "de"),
    ("ja", "vi"), ("vi", "ja"), ("ko", "vi"), ("vi", "ko"),
}


def load_suite(path=DATASET):
    raw = Path(path).read_bytes()
    suite = json.loads(raw)
    assert suite["kind"] == "synthetic_unreferenced_diagnostic"
    cases = suite["cases"]
    assert len(cases) == 16
    seen = set()
    counts = Counter()
    for case in cases:
        assert case["id"] not in seen
        seen.add(case["id"])
        pair = (case["source_language"], case["target_language"])
        assert pair in PAIRS
        assert case["category"] in {"structured", "narrative_long"}
        counts[(pair, case["category"])] += 1
        text = case["source_text"]
        assert 1 <= len(text) <= 1000
        assert text.strip()
        for literal in case["required_literals"]:
            assert literal in text
        assert case["quality_reference"] is None
    assert all(counts[(pair, category)] == 1 for pair in PAIRS
               for category in ("structured", "narrative_long"))
    return suite, hashlib.sha256(raw).hexdigest()


def assess_fidelity(case, output, finish_reason=None):
    """Deterministic warnings, NOT a substitute for reference/human translation scoring."""
    warnings = []
    if not output or not output.strip():
        warnings.append("empty_output")
    for literal in case["required_literals"]:
        if literal not in output:
            warnings.append("missing_literal:" + literal)
    if "<think>" in output or "</think>" in output:
        warnings.append("thinking_tokens_exposed")
    if finish_reason == "length":
        warnings.append("output_token_cap_reached")
    if case["category"] == "narrative_long":
        if len(output.strip()) < len(case["source_text"]) * 0.2:
            warnings.append("suspiciously_short_output")
        if "\n" in case["source_text"] and "\n" not in output:
            warnings.append("source_paragraph_breaks_lost")
    return warnings


def save_reports(report, path_json):
    path_json = Path(path_json)
    path_json.parent.mkdir(parents=True, exist_ok=True)
    path_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cases = report["run"]["cases"]
    fields = ["id", "pair", "category", "input_characters", "output_characters",
              "elapsed_seconds", "prompt_tokens", "completion_tokens",
              "tokens_per_second", "finish_reason", "warnings", "error"]
    with path_json.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for c in cases:
            writer.writerow({k: json.dumps(c[k], ensure_ascii=False)
                             if k == "warnings" else c.get(k, "") for k in fields})
    passed = sum(bool(c.get("output")) and not c.get("error") for c in cases)
    flagged = sum(bool(c.get("warnings")) for c in cases)
    lines = [
        "# Hy-MT2 L40S — Synthetic diagnostic results",
        "",
        "**Caution:** Not a certified quality benchmark; no human-reviewed reference translations.",
        "Do not report BLEU/COMET/translation accuracy from this diagnostic.",
        "",
        f"- Status: {report['run']['status']}",
        f"- Completed outputs: {passed}/{len(cases)}",
        f"- Cases with automatic fidelity warnings: {flagged}",
        f"- Modal client call wall time: {report.get('modal_rpc_wall_seconds')} seconds "
        "(includes scheduling, but not an external HTTP gateway benchmark)",
        f"- Server load to ready: {report['run'].get('model_load_seconds')} seconds",
        f"- Highest sampled GPU memory: {report['run'].get('max_sampled_gpu_mib')} MiB "
        "(200 ms sampling, not exact peak)",
        f"- Dataset SHA256: {report['dataset_sha256']}",
        "",
        "| Case | Time (s) | Completion tokens | Warnings |",
        "|---|---:|---:|---|",
    ]
    for c in cases:
        flags = ", ".join(c.get("warnings", [])) or "none"
        lines.append(f"| {c['id']} | {c.get('elapsed_seconds', '')} | "
                     f"{c.get('completion_tokens', '')} | {flags} |")
    lines += [
        "",
        "## Human review required",
        "",
        "Compare each source and output in the JSON report for adequacy, fluency, "
        "named entities, numbers, negation, omitted clauses, added meaning, honorifics, "
        "paragraph breaks and domain terminology. Use qualified DE/JA/KO reviewers.",
        "",
        "Historical baseline note: the initial CPU gateway used simulated inference.",
        "",
    ]
    path_json.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    return path_json, path_json.with_suffix(".csv"), path_json.with_suffix(".md")
