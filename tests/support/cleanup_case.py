from contextlib import contextmanager

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from tests.support import claude_factory, codex_factory, cursor_factory, grok_factory


@contextmanager
def case(tmp_path, provider="claude"):
    factory = {
        "claude": claude_factory,
        "grok": grok_factory,
        "cursor": cursor_factory,
        "codex": codex_factory,
    }[provider]
    root = SourceRoot.create(provider, tmp_path / provider, executable_version="synthetic")
    first = factory.make(root.path, "selected")
    neighbor = factory.make(root.path, "neighbor")
    data = tmp_path / "manager"
    cfg = Config(data, tmp_path / "config.toml", [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        from sessions_manager.cleanup import CleanupService

        service = CleanupService(cfg, catalog)
        uid = next(s.display_id for s in catalog.sessions() if s.native_id == "selected")
        yield service, root, uid, first, neighbor


def tree_bytes(path):
    return (
        {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}
        if path.is_dir()
        else path.read_bytes()
    )
