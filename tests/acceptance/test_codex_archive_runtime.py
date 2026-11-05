import pytest


def test_native_codex_archive_runtime_gate(request):
    executable = request.config.getoption("--codex-archive-executable")
    if executable is None:
        pytest.skip("requires explicit disposable native --codex-archive-executable")
    from tests.support.verify_native_codex_archive import verify

    result = verify(executable)
    assert result["manager_coordinator"] and result["original_flags_restored"]
    assert result["history_and_ids_preserved"] and result["neighbor_preserved"]
