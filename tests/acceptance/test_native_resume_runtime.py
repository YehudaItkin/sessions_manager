import json

import pytest

from tests.support.native_resume_gate import verify


@pytest.mark.parametrize("provider", ["claude", "grok", "cursor"])
def test_native_current_terminal_loads_exact_disposable_history(request, provider):
    executable = request.config.getoption("--" + provider + "-resume-executable")
    if executable is None:
        pytest.skip("requires explicit disposable native resume opt-in")
    result = verify(provider, executable)
    print(json.dumps(result))
    assert result["conversation_loaded"], "native resume remains unverified: " + result["startup"]
