from notebook_test_support import EXPECTED_MODELS, FakeGateway, execute, gpu_environment, initialize


def test_full_comparison_uses_four_models_and_separate_job_kinds():
    state = initialize()
    execute(state)
    assert tuple(run["model"] for run in state["benchmark_result"]["runs"]) == EXPECTED_MODELS
    assert state["translation_result"]["kind"] == "translation"
    assert state["benchmark_result"]["kind"] == "benchmark"

def test_one_model_comparison_still_performs_both_endpoints():
    state = initialize()
    state["MULTI_MODEL_KEYS"] = ["qwen35_35b"]
    execute(state)
    assert len(state["benchmark_result"]["runs"]) == 1

def test_gpu_selected_models_produce_sixteen_model_runs(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()
    execute(state, mode="gpu", fake=FakeGateway())
    jobs = [state["translation_result"], state["warmup_result"], *state["benchmark_results"]]
    assert len(jobs) == 5
    assert sum(len(job["runs"]) for job in jobs) == 16
    assert all(not run["is_mock_result"] for job in jobs for run in job["runs"])


def test_html_comparison_is_escaped_and_shows_missing_metrics():
    state = initialize()
    execute(state)
    job = state["benchmark_result"]
    job["runs"][0]["translation_text"] = '<script>alert("unsafe")</script> & text'
    job["runs"][1]["model"] = 'bad<img src=x onerror=alert(1)>'
    markup = state["_comparison_html"](job, source_text="<b>English & source</b>")
    assert "<script>" not in markup
    assert "<img" not in markup
    assert "<b>English" not in markup
    assert "&lt;script&gt;" in markup
    assert "&lt;img" in markup
    assert "&amp; text" in markup
    assert "&lt;b&gt;English &amp; source&lt;/b&gt;" in markup
    assert markup.count("<tr>") == 5
    assert "N/A" in markup


def test_html_metrics_are_reported_from_actual_response_not_fabricated():
    state = initialize()
    execute(state)
    job = state["benchmark_result"]
    run = job["runs"][0]
    run["usage"] = {"prompt_tokens": 21, "completion_tokens": 13}
    run["timings"] = {"inference_ms": 234.56}
    run["resources"] = {
        "sampled_vram_mib": 1000,
        "sampled_gpu_utilization_percent": 67.8,
    }
    markup = state["_comparison_html"](job)
    assert "21 / 13" in markup
    assert "234.56 ms" in markup
    assert "1,000 MiB" in markup
    assert "67.80%" in markup
    assert "N/A" in markup  # missing metrics for other models


def test_metric_nonfinite_or_unapproved_values_are_not_rendered():
    state = initialize()
    execute(state)
    job = state["benchmark_result"]
    run = job["runs"][0]
    run["usage"] = {"prompt_tokens": "PRIVATE_TOKEN", "completion_tokens": -5}
    run["resources"] = {"sampled_gpu_utilization_percent": float("nan"),
                        "private_value": 12345}
    markup = state["_comparison_html"](job)
    assert "PRIVATE_TOKEN" not in markup
    assert "12345" not in markup
    assert "nan%" not in markup
    assert "N/A" in markup


def test_failed_or_missing_gpu_translation_does_not_start_benchmark(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    original = fake.__call__

    def incomplete(method, path, **kwargs):
        status, result = original(method, path, **kwargs)
        if method == "GET" and path.startswith("/v1/jobs/"):
            result["runs"][0]["translation_text"] = None
        return status, result

    import pytest
    with pytest.raises(RuntimeError, match="thiếu bản dịch|no translation"):
        execute(state, mode="gpu", fake=incomplete)
    assert len(fake.posts) == 1


def test_unverified_gpu_attempt_is_never_labeled_real():
    state = initialize()
    execute(state)
    job = state["benchmark_result"]
    run = job["runs"][0]
    run["is_mock_result"] = False
    run["status"] = "failed"
    run["translation_text"] = None
    markup = state["_comparison_html"](job)
    assert "failed · UNVERIFIED" in markup
    assert "failed · REAL" not in markup


def test_error_code_table_does_not_render_arbitrary_error_text():
    state = initialize()
    execute(state)
    job = state["benchmark_result"]
    run = job["runs"][0]
    run["error_code"] = "<script>alert('secret')</script>"
    markup = state["_comparison_html"](job)
    assert "<script>" not in markup
    assert "alert" not in markup
    run["error_code"] = "model_not_ready"
    assert "model_not_ready" in state["_comparison_html"](job)


def test_report_median_uses_actual_all_three_round_metrics():
    state = initialize()
    execute(state)
    model = state["MODEL_KEYS"][0]
    for job, ms, queue, tps in zip(
        state["benchmark_results"], [200.0, 120.0, 310.0],
        [750.0, 400.0, 900.0], [45.0, 60.0, 35.0],
    ):
        run = next(r for r in job["runs"] if r["model"] == model)
        run["timings"] = {
            "inference_ms": ms, "queue_ms": queue,
            "total_ms": ms + queue, "tokens_per_second": tps,
        }
        run["resources"] = {"sampled_vram_mib": 31000.0}
    result = state["_build_three_round_summary"](
        state["benchmark_results"], state["MULTI_MODEL_KEYS"]
    )
    assert result[model]["median"]["inference_ms"] == 200.0
    assert result[model]["median"]["queue_ms"] == 750.0
    assert result[model]["median"]["tokens_per_second"] == 45.0
    assert result[model]["median"]["sampled_vram_mib"] == 31000.0
    assert result[state["MODEL_KEYS"][1]]["median"]["inference_ms"] is None
    markup = state["_summary_html"](result)
    assert "200.00 ms" in markup
    assert "N/A" in markup
    assert markup.count("<details") == 3


def test_warmup_metrics_are_separate_from_three_measured_rounds():
    state = initialize()
    output = execute(state)
    assert "\nWarm-up observations" in output
    assert "\\nWarm-up observations" not in output
    warmup = [state["translation_result"], state["warmup_result"]]
    latest = [r for job in warmup for r in job["runs"]]
    assert {r["model"] for r in latest} == set(state["MODEL_KEYS"])
    latest[0]["timings"] = {"queue_ms": 35500.0, "inference_ms": 700.0}
    markup = state["_warmup_html"](warmup)
    assert "35,500.00 ms" in markup
    assert "700.00 ms" in markup
    assert "N/A" in markup
    assert state["comparison_summary"][state["MODEL_KEYS"][0]]["median"]["queue_ms"] is None


def test_summary_escapes_model_names_and_rejects_non_numeric_metrics():
    state = initialize()
    execute(state)
    fake = { '<script>unsafe</script>': {
        "median": {"inference_ms": None, "queue_ms": None, "total_ms": None,
                   "tokens_per_second": None, "sampled_vram_mib": None},
        "rounds": [{"inference_ms": "TOKEN"}] * 3
    }}
    markup = state["_summary_html"](fake)
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert "TOKEN" not in markup
    assert "N/A" in markup


def test_alternate_locale_vi_preserved_while_english_is_default():
    state = initialize()
    assert state["DISPLAY_LANGUAGE"] == "en"
    execute(state)
    assert "Inference median" in state["_summary_html"](state["comparison_summary"])
    state["DISPLAY_LANGUAGE"] = "vi"
    assert "Inference trung vị" in state["_summary_html"](state["comparison_summary"])
