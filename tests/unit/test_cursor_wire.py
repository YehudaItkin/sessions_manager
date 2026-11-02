import pytest

from sessions_manager.models import Failure
from sessions_manager.sources.cursor_wire import fields
from tests.support.cursor_factory import wire


def test_projection_and_bounds():
    assert fields(wire(1, "hello"))[1] == [b"hello"]
    for blob in (b"\x80" * 11, b"\x0a\xff\x7f", b"\x0f"):
        with pytest.raises(Failure):
            fields(blob)
    with pytest.raises(Failure):
        fields(b"x" * (32 * 1024 * 1024 + 1))
