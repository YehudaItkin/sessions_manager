import tomllib

import pytest

from sessions_manager.models import Failure
from sessions_manager.warp import config_text


def test_fixed_config_hides_all_session_metadata(tmp_path):
    text = config_text("/safe/python", tmp_path / "manager", "a" * 64)
    config = tomllib.loads(text)
    assert config["panes"][0]["directory"] == "/"
    assert config["panes"][0]["shell"] == "zsh"
    assert len(config["panes"][0]["commands"]) == 1
    assert "_launch" in text
    assert "resume" not in text


def test_warp_template_delimiters_rejected():
    with pytest.raises(Failure):
        config_text("/python", "/data/{{unsafe}}", "a" * 64)
