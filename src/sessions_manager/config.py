"""Private manager paths and explicit native bindings."""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

from .fsops import trusted_directory
from .models import Failure, SourceRoot

DEFAULT_DATA = Path.home() / "Library/Application Support/sessions-manager"


def ensure_private(path: Path):
    try:
        return trusted_directory(path, private=True, create=True)
    except (Failure, OSError, ValueError):
        raise Failure("unsafe_data_dir", 6) from None


def private_file(path: Path, content: bytes):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


@dataclass
class Config:
    data_dir: Path
    config_path: Path
    roots: list[SourceRoot]
    discovery_roots_mode: str = "extend"

    @classmethod
    def load(cls, config_path=None, data_dir=None):
        data = Path(data_dir or DEFAULT_DATA).expanduser().absolute()
        path = Path(config_path or data / "config.toml").expanduser().absolute()
        raw = {}
        if path.exists():
            try:
                raw = tomllib.loads(path.read_text())
            except (ValueError, OSError):
                raise Failure("invalid_config", 2) from None
        mode = raw.get("discovery_roots_mode", "extend")
        if mode not in ("extend", "replace"):
            raise Failure("invalid_config", 2)
        sources = raw.get("sources", [])
        if not isinstance(sources, list) or any(not isinstance(item, dict) for item in sources):
            raise Failure("invalid_config", 2)
        roots = []
        if mode != "replace":
            homes = {
                "codex": Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
                "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")),
                "grok": Path.home() / ".grok",
                "cursor": Path.home() / ".cursor",
            }
            for provider, home in homes.items():
                command = "cursor-agent" if provider == "cursor" else provider
                binary = shutil.which(command)
                if provider == "grok" and not binary:
                    candidate = Path.home() / ".grok/bin/grok"
                    binary = str(candidate) if candidate.is_file() else None
                roots.append(
                    SourceRoot.create(
                        provider,
                        home,
                        default_root=True,
                        executable_path=Path(binary).absolute() if binary else None,
                        resume_context="native",
                    )
                )
        for item in sources:
            try:
                provider, source = item["provider"], Path(item["path"]).expanduser()
                if not source.is_absolute():
                    raise ValueError("absolute root required")
                executable = item.get("executable")
                if executable and not Path(executable).is_absolute():
                    raise ValueError("absolute executable required")
                root = SourceRoot.create(
                    provider,
                    source,
                    item.get("namespace", "default"),
                    enabled=item.get("enabled", True),
                    root_kind="explicit",
                    executable_path=Path(executable) if executable else None,
                    executable_version=item.get("executable_version"),
                    resume_context=item.get("resume_context")
                    if item.get("resume_context") == "native"
                    else None,
                )
                roots = [r for r in roots if r.root_id != root.root_id]
                roots.append(root)
            except (KeyError, ValueError, TypeError):
                raise Failure("invalid_config", 2) from None
        return cls(data, path, roots, mode)

    def prepare(self):
        data = self.data_dir.resolve()
        for root in self.roots:
            source = root.path.resolve()
            if data.is_relative_to(source) or source.is_relative_to(data):
                raise Failure("data_dir_source_overlap", 6)
        lexical = self.data_dir.absolute()
        for name in (".codex", ".claude", ".grok", ".cursor"):
            source = Path.home() / name
            if lexical.is_relative_to(source) or source.is_relative_to(lexical):
                raise Failure("data_dir_source_overlap", 6)
        os.umask(0o077)
        self.data_dir = ensure_private(self.data_dir)
        for name in ("trash", "launches"):
            ensure_private(self.data_dir / name)

    def add_source(self, provider, path, namespace="default"):
        from .models import PROVIDERS

        if provider not in PROVIDERS or not Path(path).is_absolute():
            raise Failure("invalid_source", 2)
        source = Path(path).resolve()
        data = self.data_dir.resolve()
        if source.is_relative_to(data) or data.is_relative_to(source):
            raise Failure("data_dir_source_overlap", 2)
        if self.config_path.exists():
            raw = tomllib.loads(self.config_path.read_text())
        else:
            raw = {"discovery_roots_mode": self.discovery_roots_mode}
        raw.setdefault("sources", []).append(
            {"provider": provider, "path": str(path), "namespace": namespace}
        )
        parent = trusted_directory(self.config_path.parent, create=True, owned=False)
        self.config_path = parent / self.config_path.name
        temporary = self.config_path.with_name(self.config_path.name + ".new")
        private_file(temporary, tomli_w.dumps(raw).encode())
        os.replace(temporary, self.config_path)
