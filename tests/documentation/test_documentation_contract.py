"""CPU-only contract checks for public documentation and source metadata."""
import re
from pathlib import Path


def test_readme_evidence_links_and_idempotency_explanation(published_readmes):
    root = Path(__file__).resolve().parents[2]
    evidence = (
        "deployed_gpu_readiness.json",
        "four_gpu_parallel_inference.json",
        "gpu_api_translation.json",
        "gpu_api_four_model_benchmark.json",
        "unicode_input_boundary.json",
        "concurrent_model_jobs.json",
        "gpu_container_reuse.json",
        "operations_safety_snapshot.json",
    )
    for name in ("README.md", "README.vi.md"):
        body = (root / name).read_text(encoding="utf-8")
        guide_path = "docs/reliability.vi.md" if name.endswith(".vi.md") else "docs/reliability.md"
        assert guide_path in body
        guide = (root / guide_path).read_text(encoding="utf-8")
        for report in evidence:
            assert f"reports/{report}" in guide
            assert (root / "reports" / report).is_file()
        assert "Idempotency-Key" in body
        assert "HTTP 409" in body


def test_bilingual_deployment_documents_preserve_existing_secrets():
    root = Path(__file__).resolve().parents[2]
    for name in ("deployment.md", "deployment.vi.md"):
        body = (root / "docs" / name).read_text(encoding="utf-8")
        assert "modal secret create --env" in body
        assert "--from-json" in body
        assert "scripts/deployment/create_modal_secrets.py" in body
        assert "scripts/deployment/configure_huggingface_access.py" in body
        assert "HF_TOKEN" in body
        assert "multilingual-translation-ai-inference-huggingface-download" in body
        assert "--apply" in body
        assert "source .env" in body
        assert "Secret.update()" in body
        assert "1.3.5" in body
        assert "--secret-json-file" not in body
        assert "pg_dump" not in body
    for name in ("operations.md", "operations.vi.md"):
        body = (root / "docs" / name).read_text(encoding="utf-8")
        assert "pg_dump" in body and "pg_restore" in body
        assert "--no-owner" in body

def test_tagged_release_notes_have_no_markdown_code_block_indentation():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/publish-release.yml").read_text(encoding="utf-8")
    assert "dedent(english).strip()" in workflow
    assert "dedent(vietnamese).strip()" in workflow
    assert "### v1.0.0 — Initial source release" in workflow
    assert "### v1.0.0 — Bản phát hành mã nguồn đầu tiên" in workflow
    assert "### PostgreSQL setup for self-hosted deployments" not in workflow
    assert "### Cấu hình PostgreSQL khi tự triển khai" not in workflow
    assert "TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL" not in workflow


def test_license_attribution_and_model_separation():
    root = Path(__file__).resolve().parents[2]
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    notice = (root / "MODEL_LICENSE.md").read_text(encoding="utf-8")
    assert "MIT license" in notice
    assert "not the" in notice
    for model in ("Hy-MT2", "Index-Translate", "Gemma 4", "Qwen3.5"):
        assert model in notice
    assert "Apache License" in (
        root / "THIRD_PARTY_LICENSES/Apache-2.0.txt"
    ).read_text(encoding="utf-8")


def test_package_runtime_and_citation_versions_match():
    import tomllib

    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    expected_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    assert config["project"]["version"] == expected_version
    from multilingual_translation_ai_inference import __version__
    from multilingual_translation_ai_inference.api import create_api
    from multilingual_translation_ai_inference.settings import Settings

    assert __version__ == expected_version
    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    assert f"version: {expected_version}" in citation
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        api_bearer_token="offline-test-token",
        dispatcher_mode="inline-mock",
    )
    assert create_api(settings, repository=object(), dispatcher=object()).version == expected_version
    assert config["project"]["license"] == "MIT"
    assert not any("License ::" in c for c in config["project"].get("classifiers", []))
    assert (root / "CITATION.cff").exists()








def test_package_and_modal_resource_names_are_consistent():
    import tomllib

    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["name"] == "multilingual-translation-ai-inference"
    assert (root / "src/multilingual_translation_ai_inference/__init__.py").is_file()

    from multilingual_translation_ai_inference.resource_names import (
        MODAL_API_AUTH_SECRET_NAME,
        MODAL_APP_NAME,
        MODAL_GPU_WEIGHT_VOLUME_NAMES,
        MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME,
        MODAL_POSTGRESQL_CONNECTION_SECRET_NAME,
    )
    names = [MODAL_APP_NAME, MODAL_API_AUTH_SECRET_NAME,
             MODAL_POSTGRESQL_CONNECTION_SECRET_NAME,
             MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME,
             *MODAL_GPU_WEIGHT_VOLUME_NAMES.values()]
    assert all(name.startswith("multilingual-translation-ai-inference-") for name in names)
    assert all(len(name) < 64 for name in names)
    assert len(names) == len(set(names))











def test_python_ci_workflow_uses_minimal_permissions():
    root = Path(__file__).resolve().parents[2]
    for workflow in ("python-validation.yml",):
        body = (root / ".github/workflows" / workflow).read_text(encoding="utf-8")
        assert "permissions:\n  contents: read" in body









def test_ci_quickstart_runs_without_development_extra_in_new_environment():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/python-validation.yml").read_text(encoding="utf-8")
    assert "quickstart-clean-install:" in workflow
    smoke = workflow.split("  quickstart-clean-install:", 1)[1]
    assert "python -m venv .quickstart-venv" in smoke
    assert "python-version: ['3.12', '3.13']" in smoke
    assert "pip install -e '.[demo]'" in smoke
    assert "pip install -e '.[dev]'" not in smoke
    for expected in ("scripts/examples/local_demo.py", "POST 202", "GET 200",
                     "is_mock_result", "MOCK ONLY"):
        assert expected in smoke


def test_bilingual_deployment_migration_does_not_overwrite_prepared_env():
    root = Path(__file__).resolve().parents[2]
    for filename, heading in (
        ("docs/deployment.md", "## Prepare the database schema"),
        ("docs/deployment.vi.md", "## Chuẩn bị schema database"),
    ):
        text = (root / filename).read_text(encoding="utf-8")
        assert heading in text
        migration = text.split(heading, 1)[1].split("\n## ", 1)[0]
        assert "source .env" in migration
        assert "cp .env.example .env" not in migration
        assert "TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL" in migration




def test_bilingual_readme_requests_follow_real_schema_and_api_reference(published_readmes):
    import json

    from multilingual_translation_ai_inference.schemas import SubmitTranslation

    root = Path(__file__).resolve().parents[2]
    previous = None
    for filename, title in (
        ("README.md", "## API example"),
        ("README.vi.md", "## Ví dụ gọi API"),
    ):
        body = (root / filename).read_text(encoding="utf-8")
        section = body.split(title, 1)[1].split("\n## ", 1)[0]
        payloads = [json.loads(raw) for raw in re.findall(r"-d '(\{.*?\})'", section, re.DOTALL)]
        assert len(payloads) == 1
        submitted = SubmitTranslation.model_validate(payloads[0])
        reference = root / ("docs/development.vi.md" if filename.endswith(".vi.md")
                            else "docs/development.md")
        reference_payload = json.loads(re.search(
            r"```json\n(.*?)\n```", reference.read_text(encoding="utf-8"), re.DOTALL
        ).group(1))
        assert submitted == SubmitTranslation.model_validate(reference_payload)
        assert "Authorization: Bearer" in section
        assert "Idempotency-Key" in section and "status_url" in section
        if previous is not None:
            assert payloads == previous
        previous = payloads
        assert reference.relative_to(root).as_posix() in section


def test_single_tenant_access_scope_is_documented_in_both_languages(published_readmes):
    root = Path(__file__).resolve().parents[2]
    from multilingual_translation_ai_inference.settings import Settings

    assert Settings.__dataclass_fields__["request_owner"].default == "single-tenant-api"
    for readme, config in (
        ("README.md", "docs/configuration.md"),
        ("README.vi.md", "docs/configuration.vi.md"),
    ):
        summary = (root / readme).read_text(encoding="utf-8")
        detail = (root / config).read_text(encoding="utf-8")
        assert "single-tenant" in summary.lower() and "single-tenant" in detail.lower()
        assert "single-tenant-api" in detail
        assert "Bearer" in summary and "Bearer" in detail
        assert "quota" in detail
        assert "idempotency" in summary and "idempotency" in detail
        assert "UUID" in summary and "UUID" in detail
        assert "multi-tenant" in detail.lower()
        assert config in summary










def test_readme_weight_sizes_match_manifest(published_readmes):
    import json
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "models/four_l40s_workers_q8_0_manifest.json").read_text()
    )
    total = sum(v["gguf_size_bytes"] for v in manifest["models"].values())
    assert len(manifest["models"]) == 4
    for name, decimal in (("README.md", "."), ("README.vi.md", ",")):
        body = (root / name).read_text()
        assert "models/four_l40s_workers_q8_0_manifest.json" in body
        assert f"{total/1e9:.2f}".replace(".", decimal) in body
        assert f"{total/2**30:.2f}".replace(".", decimal) in body








def _release_workflow_shell_step(step_name):
    """Extract the actual Actions shell step without adding a YAML test dependency."""
    lines = (Path(__file__).resolve().parents[2] /
             ".github/workflows/publish-release.yml").read_text(encoding="utf-8").splitlines()
    name = f"      - name: {step_name}"
    assert lines.count(name) == 1
    index = lines.index(name) + 1
    end = next((i for i in range(index, len(lines))
                if lines[i].startswith("      - name: ")), len(lines))
    block = lines[index:end]
    assert "        run: |" in block
    start = block.index("        run: |") + 1
    result = []
    for line in block[start:]:
        assert not line.strip() or line.startswith("          "), line
        result.append(line[10:] if line.strip() else "")
    return "\n".join(result).rstrip() + "\n"


def test_release_notes_pin_bilingual_doc_links_to_version_tag(tmp_path, published_readmes):
    """Release pages must not inherit relative paths from the source CHANGELOGs."""
    import os
    import subprocess

    root = Path(__file__).resolve().parents[2]
    script = _release_workflow_shell_step("Prepare bilingual release notes")
    env = {
        **os.environ,
        "GITHUB_REF_NAME": "v1.0.0",
        "GITHUB_REPOSITORY": "dangkhoa2016/Multilingual-Translation-AI-Inference",
        "RUNNER_TEMP": str(tmp_path),
    }
    result = subprocess.run(["bash", "-e", "-c", script], cwd=root, env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    notes = (tmp_path / "translation-release-notes.md").read_text(encoding="utf-8")
    prefix = ("https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference"
              "/blob/v1.0.0/")
    for relative in (
        "README.md", "docs/deployment.md", "notebooks/translation_api_demo.ipynb",
        "README.vi.md", "docs/deployment.vi.md", "docs/security.md", "docs/security.vi.md",
    ):
        assert f"]({prefix}{relative})" in notes
        assert (root / relative).is_file()
    assert not re.search(r"\]\((?:\./)?docs/", notes)
    assert "## English" in notes and "## Tiếng Việt" in notes
    assert notes.count('DEMO_MODE="offline"') == 2
    assert notes.count('DEMO_MODE="gpu"') == 2
    assert "Run All" in notes
    assert "idempotency" in notes
    assert "hidden Secrets" in notes
    assert "idempotency" in notes
    assert "GET-only recovery" in notes
    assert "khôi phục chỉ GET" in notes
    assert "the same three texts" in notes
    assert "16 actual API jobs" in notes
    assert "16 job API thật" in notes
    assert "defaults to English" in notes
    assert "Secrets ẩn" in notes
    assert "/blob/main/docs/" not in notes

    wrong_env = {**env, "GITHUB_REF_NAME": "v99.0.0"}
    rejected = subprocess.run(["bash", "-e", "-c", script], cwd=root, env=wrong_env,
                              capture_output=True, text=True, check=False)
    assert rejected.returncode != 0


def test_release_guard_updates_only_when_tag_matches_current_main(tmp_path):
    """Never publish or update release notes for a stale or divergent tag."""
    import os
    import subprocess

    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/publish-release.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in workflow
    assert "persist-credentials: false" in workflow
    assert "RELEASE_ALREADY_EXISTS" not in workflow
    assert 'gh release edit "${GITHUB_REF_NAME}"' in workflow
    assert 'gh release create "${GITHUB_REF_NAME}"' in workflow
    script = _release_workflow_shell_step("Verify version tag and current main")
    assert 'test "$tagged_sha" = "$main_sha"' in script

    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Synthetic Release Test")
    git("config", "user.email", "synthetic@example.test")
    (repo / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    git("-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "tag commit")
    old_tag = git("rev-parse", "HEAD")
    git("-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "newer main")
    main_head = git("rev-parse", "HEAD")
    git("checkout", "-q", "--detach", old_tag)
    git("-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "divergent commit")
    divergent = git("rev-parse", "HEAD")
    assert len({old_tag, main_head, divergent}) == 3

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = api ]; then printf "%s\\n" "$FAKE_MAIN_SHA"; exit 0; fi\n'
        'if [ "$1" = release ] && [ "$2" = view ]; then\n'
        '  [ "$FAKE_RELEASE_EXISTS" = 1 ]; exit $?\n'
        'fi\nexit 3\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)

    def verify(tagged, attempt, release_exists, expected, version="v1.0.0"):
        git("checkout", "-q", "--detach", tagged)
        env = {
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "FAKE_MAIN_SHA": main_head,
            "FAKE_RELEASE_EXISTS": "1" if release_exists else "0",
            "GITHUB_REF_NAME": version,
            "GITHUB_REPOSITORY": "dangkhoa2016/Multilingual-Translation-AI-Inference",
            "GITHUB_RUN_ATTEMPT": str(attempt),
            "GITHUB_ENV": str(tmp_path / "release-env"),
        }
        result = subprocess.run(["bash", "-c", script], cwd=repo, env=env,
                                capture_output=True, text=True, check=False)
        assert (result.returncode == 0) is expected, (
            tagged, attempt, release_exists, result.stderr
        )

    verify(main_head, 1, False, True)  # First publication is at main.
    verify(main_head, 1, True, True)   # Current release can be updated safely.
    verify(old_tag, 1, False, False)   # An old tag cannot be newly published.
    verify(old_tag, 1, True, False)    # Old tag cannot mutate existing release.
    verify(old_tag, 2, True, False)    # Rerun after main moves still fails.
    verify(old_tag, 2, False, False)   # Missing release does not bypass guard.
    verify(divergent, 2, True, False)  # Divergent history fails closed.
    verify(main_head, 1, False, False, version="v99.0.0")
