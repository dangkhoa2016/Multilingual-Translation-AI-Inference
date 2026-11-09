from notebook_test_support import FakeGateway, execute, gpu_environment, initialize


def test_output_omits_private_token_and_idempotency_key(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()
    output = execute(state, mode="gpu", fake=FakeGateway())
    assert "synthetic-private-test-token-123456" not in output
    assert "full-demo-" not in output
    assert "translation.example.test" not in output

def test_metrics_include_only_allowlisted_finite_numbers():
    state = initialize()
    metrics = state["_safe_run_metrics"]({
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7, "secret": 200},
        "timings": {"inference_ms": 120.0, "queue_ms": float("nan")},
        "resources": {"sampled_gpu_utilization_percent": 40.0},
        "private_key": 1000,
    })
    assert metrics == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7,
                       "inference_ms": 120.0, "sampled_gpu_utilization_percent": 40.0}

def test_offline_output_marked_synthetic():
    assert "MOCK" in execute(initialize())


def test_notebook_output_contract_is_explicit_in_both_readmes(monkeypatch):
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    for path in ("README.md", "README.vi.md"):
        text = (repo_root / path).read_text(encoding="utf-8")
        assert "SHOW_TRANSLATIONS" not in text
    assert "complete translation text" in (repo_root / "README.md").read_text()
    assert "toàn bộ nội dung bản dịch" in (repo_root / "README.vi.md").read_text()

    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    output = execute(state, mode="gpu", fake=fake)
    sentinel = "[LOCAL TEST STUB] hy_mt2_30b"
    assert sentinel in output
    assert sentinel in state["_comparison_html"](state["benchmark_result"])


def test_intro_both_languages_match_default_sequence():
    from notebook_test_support import source

    intro = source("intro")
    assert "16 real API jobs" in intro
    assert "16 API jobs / 16 model-runs" in intro
    assert "5 API jobs / 16 model-runs" in intro
    assert "five stages" not in intro
