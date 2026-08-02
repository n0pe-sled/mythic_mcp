"""Versioned documentation indexing for Mythic payload repositories."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_TEXT_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
_ROOT_DOCUMENTS = {"readme.md", "readme.mdx", "agent_capabilities.json"}
_WORD = re.compile(r"[a-z0-9_:+.-]+")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class DocumentationChunk:
    path: str
    heading: str
    text: str
    source_url: str


@dataclass
class PayloadDocumentation:
    payload_type: str
    repository_url: str
    requested_ref: str | None
    commit: str
    capabilities: dict[str, Any]
    chunks: list[DocumentationChunk]


class PayloadDocumentationStore:
    """Read and cache documentation without checking out or executing repositories."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = (cache_dir or Path.home() / ".cache" / "mythic-mcp" / "docs").expanduser()
        self._indexes: dict[str, PayloadDocumentation] = {}

    async def index(
        self,
        payload_type: str,
        repository_url: str,
        ref: str | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._index, payload_type, repository_url, ref, refresh
        )

    def _index(
        self,
        payload_type: str,
        repository_url: str,
        ref: str | None,
        refresh: bool,
    ) -> dict[str, Any]:
        local_repository = Path(repository_url).expanduser()
        if local_repository.exists():
            repository_url = str(local_repository.resolve())
        elif not re.match(r"^(https?://|ssh://|git@)", repository_url):
            raise ValueError(
                "repository_url must be a local path or an HTTP(S)/SSH Git URL"
            )
        key = self._key(payload_type)
        if not refresh:
            existing = self._load(key)
            if (
                existing is not None
                and existing.repository_url == repository_url
                and existing.requested_ref == ref
            ):
                return self._summary(existing)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{key}-", dir=self.cache_dir) as temp:
            repository = Path(temp) / "repository.git"
            command = [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "clone",
                "--quiet",
                "--depth",
                "1",
                "--no-checkout",
            ]
            command.extend(["--", repository_url, str(repository)])
            self._git(command)
            if ref:
                self._git(
                    [
                        "git",
                        "-C",
                        str(repository),
                        "-c",
                        "core.hooksPath=/dev/null",
                        "fetch",
                        "--quiet",
                        "--depth",
                        "1",
                        "origin",
                        ref,
                    ]
                )
            commit = self._git(
                [
                    "git",
                    "-C",
                    str(repository),
                    "rev-parse",
                    "FETCH_HEAD" if ref else "HEAD",
                ]
            ).strip()
            paths = self._git(
                ["git", "-C", str(repository), "ls-tree", "-r", "--name-only", commit]
            ).splitlines()

            capabilities: dict[str, Any] = {}
            chunks: list[DocumentationChunk] = []
            for path in paths:
                if not self._documentation_path(path, payload_type):
                    continue
                content = self._git_bytes(
                    ["git", "-C", str(repository), "show", f"{commit}:{path}"]
                )
                if len(content) > 512_000:
                    continue
                if PurePosixPath(path).name.lower() == "agent_capabilities.json":
                    try:
                        capabilities = json.loads(content.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        pass
                    continue
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                chunks.extend(
                    self._chunks(path, text, repository_url, commit)
                )

        indexed = PayloadDocumentation(
            payload_type=payload_type,
            repository_url=repository_url,
            requested_ref=ref,
            commit=commit,
            capabilities=capabilities,
            chunks=chunks[:1000],
        )
        self._indexes[key] = indexed
        self._save(key, indexed)
        return self._summary(indexed)

    async def search(
        self, payload_type: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        index = self._require(payload_type)
        words = set(_WORD.findall(query.lower()))
        if not words:
            return []
        scored: list[tuple[int, DocumentationChunk]] = []
        for chunk in index.chunks:
            heading = chunk.heading.lower()
            text = chunk.text.lower()
            path = chunk.path.lower()
            score = sum(
                8 * path.count(word) + 5 * heading.count(word) + text.count(word)
                for word in words
            )
            if score:
                scored.append((score, chunk))
        scored.sort(key=lambda entry: (-entry[0], entry[1].path, entry[1].heading))
        return [
            {"score": score, **asdict(chunk)}
            for score, chunk in scored[: max(1, min(limit, 20))]
        ]

    def get(self, payload_type: str) -> dict[str, Any] | None:
        index = self._load(self._key(payload_type))
        if index is None:
            return None
        return {
            "payload_type": index.payload_type,
            "repository_url": index.repository_url,
            "requested_ref": index.requested_ref,
            "commit": index.commit,
            "capabilities": index.capabilities,
            "documents": sorted({chunk.path for chunk in index.chunks}),
        }

    async def command_docs(
        self, payload_type: str, command_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        index = self._require(payload_type)
        exact = [
            chunk
            for chunk in index.chunks
            if PurePosixPath(chunk.path).stem.lower() == command_name.lower()
        ]
        if exact:
            return [asdict(chunk) for chunk in exact[: max(1, min(limit, 20))]]
        return await self.search(payload_type, f"{command_name} command usage output", limit)

    def _require(self, payload_type: str) -> PayloadDocumentation:
        index = self._load(self._key(payload_type))
        if index is None:
            raise ValueError(
                f"No documentation is indexed for {payload_type}; call index_payload_docs first"
            )
        return index

    def _load(self, key: str) -> PayloadDocumentation | None:
        if key in self._indexes:
            return self._indexes[key]
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        data["chunks"] = [DocumentationChunk(**chunk) for chunk in data["chunks"]]
        index = PayloadDocumentation(**data)
        self._indexes[key] = index
        return index

    def _save(self, key: str, index: PayloadDocumentation) -> None:
        path = self.cache_dir / f"{key}.json"
        path.write_text(json.dumps(asdict(index), indent=2), encoding="utf-8")

    @staticmethod
    def _summary(index: PayloadDocumentation) -> dict[str, Any]:
        return {
            "payload_type": index.payload_type,
            "repository_url": index.repository_url,
            "requested_ref": index.requested_ref,
            "commit": index.commit,
            "capabilities": index.capabilities,
            "documents": len({chunk.path for chunk in index.chunks}),
            "chunks": len(index.chunks),
        }

    @staticmethod
    def _key(payload_type: str) -> str:
        name = re.sub(r"[^a-z0-9_.-]+", "-", payload_type.lower()).strip("-.")
        if not name:
            raise ValueError("payload_type must contain a letter or number")
        return f"{name}-{hashlib.sha256(payload_type.encode()).hexdigest()[:8]}"

    @staticmethod
    def _documentation_path(path: str, payload_type: str) -> bool:
        item = PurePosixPath(path)
        name = item.name.lower()
        lowered_parts = [part.lower() for part in item.parts]
        suffix = item.suffix.lower()
        if len(item.parts) == 1 and name in _ROOT_DOCUMENTS:
            return True
        if suffix not in _TEXT_SUFFIXES:
            return False
        documentation_directory = any(
            part in {"docs", "doc", "documentation", "documentation-payload"}
            or part.startswith("documentation-")
            for part in lowered_parts[:-1]
        )
        payload_scoped = payload_type.lower() in lowered_parts or not any(
            part.startswith("documentation-") for part in lowered_parts
        )
        return documentation_directory and payload_scoped

    @staticmethod
    def _chunks(
        path: str, content: str, repository_url: str, ref: str
    ) -> list[DocumentationChunk]:
        source = PayloadDocumentationStore._source_url(repository_url, ref, path)
        heading = PurePosixPath(path).name
        lines: list[str] = []
        chunks: list[DocumentationChunk] = []

        def flush() -> None:
            text = "\n".join(lines).strip()
            if text:
                for start in range(0, len(text), 4000):
                    chunks.append(
                        DocumentationChunk(
                            path=path,
                            heading=heading,
                            text=text[start : start + 4000],
                            source_url=source,
                        )
                    )

        for line in content.splitlines():
            match = _HEADING.match(line)
            if match:
                flush()
                lines = []
                heading = match.group(2).strip()
            else:
                lines.append(line)
        flush()
        return chunks

    @staticmethod
    def _source_url(repository_url: str, ref: str, path: str) -> str:
        match = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?$", repository_url)
        if match:
            return f"https://github.com/{match.group(1)}/blob/{ref}/{path}"
        return f"{repository_url}@{ref}:{path}"

    @staticmethod
    def _git(command: list[str]) -> str:
        return PayloadDocumentationStore._git_bytes(command).decode("utf-8")

    @staticmethod
    def _git_bytes(command: list[str]) -> bytes:
        try:
            return subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            ).stdout
        except subprocess.CalledProcessError as error:
            message = error.stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(f"Unable to read payload documentation: {message}") from error
