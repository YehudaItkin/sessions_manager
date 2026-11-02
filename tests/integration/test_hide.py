from sessions_manager.discovery import refresh
from tests.support.cleanup_case import case, tree_bytes


def test_hide_refresh_and_unhide_no_native_changes(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        before = tree_bytes(root.path)
        session = service.catalog.get(uid)
        service.catalog.hide([session.session_uid], True)
        refresh(service.config, service.catalog)
        assert service.catalog.get(uid).hidden
        service.catalog.hide([session.session_uid], False)
        assert not service.catalog.get(uid).hidden
        assert tree_bytes(root.path) == before
