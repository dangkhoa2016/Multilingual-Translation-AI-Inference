import pytest
from notebook_test_support import FakeGateway, execute, gpu_environment, initialize


def test_accepted_job_can_be_polled_again_without_new_post(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    execute(state, mode="gpu", fake=fake)
    first_key = fake.posts[0][2]
    execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 5
    assert fake.posts[0][2] == first_key

def test_auto_run_id_changes_after_kernel_restart(monkeypatch):
    gpu_environment(monkeypatch)
    fake = FakeGateway()
    first = initialize()
    execute(first, mode="gpu", fake=fake)
    first_keys = [call[2] for call in fake.posts]
    second = initialize()
    execute(second, mode="gpu", fake=fake)
    assert first["DEMO_RUN_ID"] != second["DEMO_RUN_ID"]
    assert [call[2] for call in fake.posts][5:] != first_keys


def test_explicit_run_id_reuses_deterministic_keys_after_kernel_restart(monkeypatch):
    gpu_environment(monkeypatch)
    fake = FakeGateway()
    first = initialize()
    first["DEMO_RUN_ID"] = "repeatable-test-run"
    execute(first, mode="gpu", fake=fake)
    first_keys = [call[2] for call in fake.posts]
    second = initialize()
    second["DEMO_RUN_ID"] = "repeatable-test-run"
    execute(second, mode="gpu", fake=fake)
    assert [call[2] for call in fake.posts][5:] == first_keys

def test_private_job_ids_not_printed(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    output = execute(state, mode="gpu", fake=fake)
    assert state["translation_result"]["job_id"] not in output
    assert state["benchmark_result"]["job_id"] not in output


def test_read_only_recovery_after_fresh_kernel_does_not_submit_gpu_job(monkeypatch):
    gpu_environment(monkeypatch)
    fake = FakeGateway()
    first = initialize()
    execute(first, mode="gpu", fake=fake)
    job_id = first["benchmark_result"]["job_id"]
    old_posts = len(fake.posts)

    new_kernel = initialize()
    new_kernel["RECOVERY_JOB_ID"] = job_id
    output = execute(new_kernel, mode="gpu", fake=fake)
    assert "GET-ONLY RECOVERY COMPLETED" in output
    assert new_kernel["recovery_result"]["job_id"] == job_id
    assert new_kernel["translation_result"] is None
    assert new_kernel["benchmark_result"] is None
    assert len(fake.posts) == old_posts
    assert all(call[0] == "GET" for call in fake.calls[-1:])


def test_get_only_recovery_works_after_gateway_switched_to_mock(monkeypatch):
    gpu_environment(monkeypatch)
    fake = FakeGateway()
    initial = initialize()
    execute(initial, mode="gpu", fake=fake)
    job_id = initial["translation_result"]["job_id"]
    fake.phase = "mock-only"
    new_kernel = initialize()
    new_kernel["RECOVERY_JOB_ID"] = job_id
    execute(new_kernel, mode="gpu", fake=fake)
    assert len(fake.posts) == 5
    assert new_kernel["recovery_result"]["job_id"] == job_id


def test_read_only_recovery_rejects_invalid_uuid_before_network(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    state["RECOVERY_JOB_ID"] = "not-a-valid-uuid"
    with pytest.raises(ValueError, match="UUID"):
        execute(state, mode="gpu", fake=fake)
    assert not fake.calls


def test_read_only_recovery_never_runs_in_offline_mode(monkeypatch):
    state = initialize()
    state["RECOVERY_JOB_ID"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    with pytest.raises(ValueError, match="GET-only"):
        execute(state, mode="offline")


def test_recovery_result_does_not_invent_success_for_failed_job(monkeypatch):
    gpu_environment(monkeypatch)
    fake = FakeGateway()
    original = initialize()
    execute(original, mode="gpu", fake=fake)
    uuid = original["translation_result"]["job_id"]
    fake.jobs[uuid]["status"] = "failed"
    fake.jobs[uuid]["runs"][0]["status"] = "failed"
    state = initialize()
    state["RECOVERY_JOB_ID"] = uuid
    output = execute(state, mode="gpu", fake=fake)
    assert "failed" in output
    assert "FULL DEMO COMPLETED" not in output
    assert len(fake.posts) == 5


def test_access_private_accepted_uuids_without_printing_them(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    output = execute(state, mode="gpu", fake=fake)
    ids = state["accepted_demo_job_ids"]()
    assert len(ids) == 5
    assert all(i not in output for i in ids)


def test_hidden_prompt_for_recovery_uuid_keeps_id_out_of_source(monkeypatch):
    import getpass

    gpu_environment(monkeypatch)
    fake = FakeGateway()
    initial = initialize()
    execute(initial, mode="gpu", fake=fake)
    uuid = initial["benchmark_result"]["job_id"]
    original = len(fake.posts)
    monkeypatch.delenv("TRANSLATION_EXISTING_JOB_ID", raising=False)

    from test_notebook_secrets import _unavailable_platform_secrets
    _unavailable_platform_secrets(monkeypatch)
    prompts = []
    def hidden_prompt(label):
        prompts.append(label)
        return uuid
    monkeypatch.setattr(getpass, "getpass", hidden_prompt)

    new_kernel = initialize()
    new_kernel["RECOVERY_JOB_ID"] = "prompt"
    output = execute(new_kernel, mode="gpu", fake=fake)
    assert len(prompts) == 1 and "UUID" in prompts[0]
    assert len(fake.posts) == original
    assert uuid not in output
    assert uuid in new_kernel["accepted_demo_job_ids"]() or (
        new_kernel["recovery_result"]["job_id"] == uuid
    )


def test_unset_recovery_uuid_does_not_touch_live_gateway(monkeypatch):
    state, fake = initialize(), FakeGateway()
    state["RECOVERY_JOB_ID"] = "not-valid"
    with pytest.raises(ValueError):
        execute(state, mode="gpu", fake=fake)
    assert fake.calls == []
