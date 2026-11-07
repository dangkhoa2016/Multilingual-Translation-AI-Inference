"""Dispatch strategies. Modal CPU mock uses spawn(), never a GPU."""
from typing import Protocol

from .repository import JobRepository
from .resource_names import MODAL_APP_NAME, MODAL_CPU_MOCK_WORKER_FUNCTION_NAME
from .worker import process_mock_translation_run


class Dispatcher(Protocol):
    def submit(self, repo: JobRepository, run_id: str, claim_token: str) -> str | None:
        ...


class RecordOnlyDispatcher:
    """Do not dispatch; keep runs queued for testing the HTTP contract."""
    def submit(self, repo: JobRepository, run_id: str, claim_token: str) -> str | None:
        # The dispatcher is bypassed in dispatch_queued_runs; defensive fail-closed.
        raise RuntimeError("record-only mode cannot start a claimed run")
        return None


class InlineMockDispatcher:
    def submit(self, repo: JobRepository, run_id: str, claim_token: str) -> str | None:
        process_mock_translation_run(repo, run_id, claim_token)
        return None


class ModalCpuMockDispatcher:
    """In a deployed Modal app, invoke the dedicated CPU mock Function."""
    def submit(self, repo: JobRepository, run_id: str, claim_token: str) -> str | None:
        import modal
        worker = modal.Function.from_name(MODAL_APP_NAME, MODAL_CPU_MOCK_WORKER_FUNCTION_NAME)
        call = worker.spawn(run_id, claim_token)
        return getattr(call, "object_id", None)


def make_dispatcher(mode: str) -> Dispatcher:
    return {
        "record-only": RecordOnlyDispatcher,
        "inline-mock": InlineMockDispatcher,
        "modal-cpu-mock": ModalCpuMockDispatcher,
    }[mode]()


def dispatch_queued_runs(repo: JobRepository, dispatcher: Dispatcher, job_id: str,
                         owner: str) -> None:
    if isinstance(dispatcher, RecordOnlyDispatcher):
        return
    for run_id in repo.queued_run_ids(job_id, owner):
        claim_token = repo.claim_dispatch(run_id)
        if claim_token is None:
            continue
        try:
            call_id = dispatcher.submit(repo, run_id, claim_token)
            repo.record_modal_call(run_id, claim_token, call_id)
        except Exception:
            # An exception from spawn() is ambiguous: it may have been accepted.
            # Do NOT blindly resubmit; reconciliation is planned for P2.
            repo.mark_dispatch_uncertain(run_id, claim_token)
