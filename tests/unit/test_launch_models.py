import os

import pytest

from sessions_manager.models import LaunchRequest


def test_launch_model_rejects_shell_and_credentials():
    with pytest.raises(ValueError):
        LaunchRequest(
            "id", "session", {}, {}, "relative", ["relative"], "/", {}, "current", "/", os.getuid()
        )
    with pytest.raises(ValueError):
        LaunchRequest(
            "id",
            "session",
            {},
            {},
            "/bin/echo",
            ["/bin/echo"],
            "/",
            {"API_KEY": "secret"},
            "current",
            "/",
            os.getuid(),
        )
