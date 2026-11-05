import sys

import pytest

from sessions_manager.models import Failure, SourceRoot
from sessions_manager.native_archive import NativeClient


@pytest.mark.parametrize("reply", ["error", "malformed"])
def test_native_rpc_errors_are_bounded_and_never_include_native_contents(tmp_path, reply, capsys):
    executable = tmp_path / "fake-native"
    executable.write_text(
        f"#!{sys.executable}\nimport sys,json\n"
        "for line in sys.stdin:\n"
        " request=json.loads(line)\n"
        " if 'id' not in request: continue\n"
        " if request['method']=='initialize': result={'id':request['id'],'result':{}}\n"
        " else: result={'id':request['id'],'error':{'message':'PRIVATE-NATIVE-CONTENT'}}\n"
        f" if request['method']!='initialize' and {reply!r}=='malformed': print('PRIVATE-NATIVE-CONTENT',flush=True)\n"
        " else: print(json.dumps(result),flush=True)\n"
    )
    executable.chmod(0o700)
    root = SourceRoot.create("codex", tmp_path, executable_path=executable)
    with NativeClient(root) as client:
        with pytest.raises(Failure) as error:
            client.call("thread/archive", {"threadId": "synthetic"})
        assert "PRIVATE-NATIVE-CONTENT" not in str(error.value)
        with pytest.raises(Failure, match="native_archive_method_unavailable"):
            client.call("thread/delete", {"threadId": "synthetic"})
    captured = capsys.readouterr()
    assert "PRIVATE-NATIVE-CONTENT" not in captured.out + captured.err
