"""CPU-only checks for opt-in Hy-MT2 quality diagnostic; never starts GPU."""
import json

from scripts.hy_mt2_benchmark_common import (
    DATASET,
    PAIRS,
    assess_fidelity,
    load_suite,
    save_reports,
)


def test_diagnostic_all_eight_directions_and_two_case_types():
    suite, digest = load_suite()
    assert len(digest) == 64
    assert len(suite["cases"]) == 16
    assert {case["target_language"] for case in suite["cases"]} == {"vi", "en", "de", "ja", "ko"}
    assert {(c["source_language"], c["target_language"]) for c in suite["cases"]} == PAIRS
    assert all(1 <= len(c["source_text"]) <= 1000 for c in suite["cases"])


def test_diagnostic_is_explicitly_unreferenced_and_non_production():
    suite, _ = load_suite()
    assert suite["kind"] == "synthetic_unreferenced_diagnostic"
    assert all(c["quality_reference"] is None for c in suite["cases"])


def test_literal_fidelity_and_output_token_cap_checks():
    case = next(c for c in load_suite()[0]["cases"] if c["category"] == "structured")
    good = "Đơn {ORDER_ID} đã xác nhận. <b>Dễ vỡ</b>. INV-2048, SKU-A17."
    assert assess_fidelity(case, good) == []
    warnings = assess_fidelity(case, "Đơn hàng đã được xác nhận.", "length")
    assert "missing_literal:{ORDER_ID}" in warnings
    assert "output_token_cap_reached" in warnings


def test_long_passage_detects_short_or_flattened_output():
    case = next(c for c in load_suite()[0]["cases"] if c["category"] == "narrative_long")
    warnings = assess_fidelity(case, "INV-2048")
    assert "suspiciously_short_output" in warnings
    assert "source_paragraph_breaks_lost" in warnings


def test_offline_report_generation(tmp_path):
    suite, digest = load_suite()
    case = suite["cases"][0]
    report = {
        "dataset_sha256": digest, "modal_rpc_wall_seconds": 50,
        "run": {
            "status": "completed", "model_load_seconds": 20,
            "max_sampled_gpu_mib": 31000,
            "cases": [{
                "id": case["id"], "pair": "en->vi",
                "category": "structured", "input_characters": len(case["source_text"]),
                "output": "sample", "warnings": ["manual_review_required"],
                "completion_tokens": 4, "elapsed_seconds": 0.5,
            }],
        },
    }
    outputs = save_reports(report, tmp_path / "diag.json")
    assert all(p.is_file() for p in outputs)
    assert json.loads(outputs[0].read_text(encoding="utf-8"))["dataset_sha256"] == digest
    assert DATASET.is_file()


def test_recorded_gpu_diagnostic_matches_pinned_fixture_and_lock():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    report = json.loads(
        (root / "reports/p3_hy_mt2_quality_diagnostic_v1.json").read_text(encoding="utf-8")
    )
    lock = json.loads((root / "models/hy_mt2_30b_q8_0.lock.json").read_text(encoding="utf-8"))
    _, digest = load_suite()
    assert report["dataset_sha256"] == digest
    assert report["run"]["weight_sha256"] == lock["gguf"]["sha256_from_huggingface_metadata"]
    assert report["run"]["engine_revision"] == lock["llama_cpp"]["revision"]
    assert report["run"]["status"] == "completed"
    assert len(report["run"]["cases"]) == 16
    assert all(c["error"] is None and c["output"] and c["finish_reason"] == "stop"
               for c in report["run"]["cases"])
    assert report["run"]["gpu_peak_is_exact"] is False
    assert lock["verification"]["ready_for_real_inference"] is False


def test_preliminary_semantic_review_anchors_present_in_actual_outputs():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    report = json.loads(
        (root / "reports/p3_hy_mt2_quality_diagnostic_v1.json").read_text(encoding="utf-8")
    )
    review = json.loads(
        (root / "reports/p3_hy_mt2_quality_review_v1.json").read_text(encoding="utf-8")
    )
    outputs = {c["id"]: c for c in report["run"]["cases"]}
    assert review["dataset_sha256"] == report["dataset_sha256"]
    assert review["human_native_language_review_complete"] is False
    assert review["decision"] == "NOT_PRODUCTION_READY"
    assert len([i for i in review["issues"] if i["category"] == "material_substitution"]) == 4
    for issue in review["issues"]:
        case = outputs[issue["case_id"]]
        assert issue["source_text"] in case["source_text"]
        assert issue["actual_output"] in case["output"]
