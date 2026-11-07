"""Offline tests for material/glossary experiment; never allocate GPU."""
import json
from pathlib import Path

from scripts.modal_hy_mt2_material_glossary_probe import (
    DATASET,
    LEXICAL,
    PROMPTS,
    analyze_output,
    build_prompt,
    load_fixture,
)


def test_material_glossary_suite_is_frozen_and_within_api_limit():
    suite, digest = load_fixture()
    assert len(digest) == 64
    assert len(suite["cases"]) == 20
    assert set(suite["prompt_variants"]) == set(PROMPTS)
    assert all(len(c["source_text"]) <= 1000 for c in suite["cases"])
    assert sum(c["group"] == "development_retest" for c in suite["cases"]) == 4
    assert sum(c["group"] == "independent_probe" for c in suite["cases"]) == 16
    assert DATASET.is_file()
    assert all(c["source_language"] == "vi" for c in suite["cases"])


def test_target_language_coverage_and_material_lexicons():
    suite, _ = load_fixture()
    assert {x["target_language"] for x in suite["cases"]} == {"en", "de", "ja", "ko"}
    assert all({"silver", "copper", "gold"} <= set(LEXICAL[lang])
               for lang in ("en", "de", "ja", "ko"))


def test_prompts_preserve_source_text_and_do_not_use_system_message():
    suite, _ = load_fixture()
    case = suite["cases"][0]
    base = build_prompt(case, "baseline_official_v1")
    guide = build_prompt(case, "material_glossary_v1")
    assert base.endswith(case["source_text"])
    assert guide.endswith(case["source_text"])
    assert "Vietnamese 'bạc' means silver" in guide
    assert "Vietnamese 'bạc' means silver" not in base
    assert base != guide


def test_material_and_identifier_checks_are_only_indicators():
    suite, _ = load_fixture()
    case = next(c for c in suite["cases"] if c["id"] == "invoice_silver_vi_to_en")
    analysis = analyze_output(
        case, "Lâm marked silver 925, not copper, SKU-A17 / LOT-301.",
        "material_glossary_v1",
    )
    assert analysis["lexical_concepts_present"] == {"silver": True, "copper": True}
    assert analysis["missing_literal_identifiers"] == []
    assert analysis["latin_name_lam_preserved"] is True
    assert analysis["human_review_required"] is True


def test_existing_accepted_v1_results_are_left_unchanged():
    root = Path(__file__).resolve().parents[1]
    old = json.loads((root / "reports/p3_hy_mt2_quality_diagnostic_v1.json").read_text())
    assert old["run"]["status"] == "completed"
    assert len(old["run"]["cases"]) == 16
    assert old["run"]["gguf_sha256"] if "gguf_sha256" in old["run"] else old["run"]["weight_sha256"]


def test_material_hint_avoids_korean_grammatical_particle_false_positive():
    from scripts.modal_hy_mt2_material_glossary_probe import lexical_material_hint

    assert not lexical_material_hint("교수는 구리 나침반을 보고 싶어했다.", "ko", "silver")
    assert lexical_material_hint("그는 은으로 만든 나침반을 보았다.", "ko", "silver")
    assert lexical_material_hint("그는 구리 나침반을 보았다.", "ko", "copper")
    assert not lexical_material_hint("기차표 요금은 3000엔이다.", "ko", "gold")
    assert lexical_material_hint("금으로 만든 왕관", "ko", "gold")


def test_japanese_material_hint_requires_material_context():
    from scripts.modal_hy_mt2_material_glossary_probe import lexical_material_hint

    assert not lexical_material_hint("料金を確認してください。", "ja", "gold")
    assert lexical_material_hint("銀製の羅針盤", "ja", "silver")
    assert not lexical_material_hint("銅製の羅針盤", "ja", "silver")
    assert lexical_material_hint("銅製の羅針盤", "ja", "copper")
    assert lexical_material_hint("銅や金で作られていない指輪", "ja", "copper")
    assert lexical_material_hint("素材はシルバー925", "ja", "silver")


def test_recorded_glossary_gpu_results_are_immutable_source_with_offline_analysis():
    from collections import Counter

    from scripts.modal_hy_mt2_material_glossary_probe import REPORT

    suite, digest = load_fixture()
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["dataset_sha256"] == digest
    assert report["analysis_recomputed_offline_without_new_gpu_run"] is True
    assert report["result"]["status"] == "completed"
    assert report["result"]["requested_cases"] == 20
    assert len(report["result"]["records"]) == 40
    assert report["result"]["gpu_peak_is_exact"] is False
    assert report["result"]["stop_reason"] is None
    cases = {c["id"]: c for c in suite["cases"]}
    assert set(Counter(row["variant"] for row in report["result"]["records"]).values()) == {20}
    for row in report["result"]["records"]:
        assert row["error"] is None
        assert row["output"]
        assert row["analysis"] == analyze_output(cases[row["id"]], row["output"], row["variant"])


def test_manual_semantic_anchors_are_supported_by_model_outputs():
    root = Path(__file__).resolve().parents[1]
    review = json.loads(
        (root / "reports/p3_hy_mt2_material_glossary_review_v1.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (root / "reports/p3_hy_mt2_material_glossary_probe_v1.json").read_text(encoding="utf-8")
    )
    assert review["dataset_sha256"] == report["dataset_sha256"]
    assert review["native_language_human_reference_review_complete"] is False
    records = {(r["id"], r["variant"]): r for r in report["result"]["records"]}
    assert len(review["specific_findings"]) >= 7
    for issue in review["specific_findings"]:
        case_id = issue["case_id"]
        assert issue["baseline_quote"] in records[(case_id, "baseline_official_v1")]["output"]
        assert issue["glossary_quote"] in records[(case_id, "material_glossary_v1")]["output"]
