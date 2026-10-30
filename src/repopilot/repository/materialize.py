import hashlib
import re
from pathlib import Path, PurePosixPath

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.verification import FileEntry, FrozenSuite, SourceSnapshot, fingerprint
from repopilot.repository.snapshot import EXCLUDED, _git

MAX_FILES = 500
MAX_TOTAL_BYTES = 8_000_000
MAX_FILE_BYTES = 1_000_000
PRIVATE_PARTS = {
    ".aws",
    ".ssh",
    ".azure",
    ".kube",
    ".gnupg",
    ".codex",
    ".agents",
    "id_rsa",
    "id_ed25519",
}


def safe_relative(path: str) -> PurePosixPath:
    parts = PurePosixPath(path).parts
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *{f"com{i}" for i in range(10)},
        *{f"lpt{i}" for i in range(10)},
    }
    if (
        not parts
        or PurePosixPath(path).is_absolute()
        or any(char in path for char in "\\:,\x00\r\n")
        or any(
            part in {".", ".."}
            or part.endswith((".", " "))
            or part.split(".", 1)[0].casefold() in reserved
            or any(ord(char) < 32 or char in '<>"|?*' for char in part)
            for part in parts
        )
        or str(PurePosixPath(path)) != path
    ):
        raise RepoPilotError("unsafe_snapshot_path", "Snapshot contains an unsupported path.")
    return PurePosixPath(path)


def excluded(path: PurePosixPath) -> bool:
    return bool({part.casefold() for part in path.parts} & (EXCLUDED | PRIVATE_PARTS)) or any(
        part.casefold().startswith(".env") or part.casefold().endswith((".pem", ".key"))
        for part in path.parts
    )


def write_files(destination: Path, files: dict[str, bytes]) -> list[FileEntry]:
    destination.mkdir(parents=True, exist_ok=False)
    destination.chmod(0o755)
    seen = set()
    entries = []
    for name, data in sorted(files.items()):
        path = safe_relative(name)
        if name.casefold() in seen:
            raise RepoPilotError("snapshot_path_collision", "Snapshot paths collide on this host.")
        seen.add(name.casefold())
        target = destination.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        # These are controller-created regular files, never archive extraction or host imports.
        target.write_bytes(data)
        target.chmod(0o644)
        entries.append(
            FileEntry(path=name, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
        )
    return entries


def directory_digest(root: Path) -> str:
    files = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise RepoPilotError("snapshot_changed", "A snapshot contains an unsupported link.")
        if path.is_file():
            data = path.read_bytes()
            files.append(
                FileEntry(
                    path=path.relative_to(root).as_posix(),
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                ).model_dump()
            )
    return fingerprint(files)


def materialize_repository(repository: Path, ref: str, destination: Path) -> SourceSnapshot:
    commit = (
        _git(repository, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
        .decode()
        .strip()
    )
    selected = []
    omitted = []
    total = 0
    for record in _git(repository, "ls-tree", "-r", "-l", "-z", "--full-tree", commit).split(b"\0"):
        if not record:
            continue
        meta, raw_path = record.split(b"\t", 1)
        mode, kind, oid, size = meta.decode("ascii").split()
        path = raw_path.decode("utf-8")
        relative = safe_relative(path)
        if excluded(relative):
            omitted.append(path)
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise RepoPilotError(
                "unsupported_snapshot_entry", "Symlinks and submodules are not executable inputs."
            )
        total += int(size)
        if int(size) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(selected) >= MAX_FILES:
            raise RepoPilotError(
                "snapshot_too_large", "Execution snapshot exceeds the configured limits."
            )
        selected.append((path, oid, int(size)))
    if not selected:
        raise RepoPilotError("empty_snapshot", "Execution snapshot has no allowed regular files.")
    blobs = _git(
        repository,
        "cat-file",
        "--batch",
        input_bytes="".join(oid + "\n" for _, oid, _ in selected).encode(),
    )
    offset = 0
    files = {}
    for name, expected_oid, expected_size in selected:
        end = blobs.index(b"\n", offset)
        oid, kind, size = blobs[offset:end].decode().split()
        if oid != expected_oid or kind != "blob" or int(size) != expected_size:
            raise RepoPilotError(
                "snapshot_invalid", "Git object does not match the fixed source tree."
            )
        files[name] = blobs[end + 1 : end + 1 + expected_size]
        offset = end + expected_size + 2
    entries = write_files(destination, files)
    return SourceSnapshot(
        commit=commit,
        source_digest=fingerprint([entry.model_dump() for entry in entries]),
        files=entries,
        excluded_paths=omitted,
    )


def freeze_suite(source: Path, destination: Path) -> FrozenSuite:
    if not source.is_dir() or source.is_symlink():
        raise RepoPilotError(
            "invalid_suite", "Suite must be a regular directory of Python test files."
        )
    files = {}
    total = 0
    for path in sorted(source.rglob("*")):
        relative = safe_relative(path.relative_to(source).as_posix())
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise RepoPilotError("invalid_suite", "Suite must not contain symlinks or junctions.")
        if path.is_dir() or "__pycache__" in relative.parts:
            continue
        if path.suffix != ".py" or excluded(relative):
            raise RepoPilotError(
                "invalid_suite", "Only Python files are allowed in a frozen suite."
            )
        if path.stat().st_size > 128_000:
            raise RepoPilotError("invalid_suite", "Frozen suite exceeds its size limit.")
        data = path.read_bytes()
        total += len(data)
        if total > 128_000 or len(files) >= 50:
            raise RepoPilotError("invalid_suite", "Frozen suite exceeds its size limit.")
        try:
            files[str(relative)] = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RepoPilotError("invalid_suite", "Frozen suite must be UTF-8.") from error
    if not any(re.fullmatch(r"test_[^/]+\.py", name) for name in files):
        raise RepoPilotError("invalid_suite", "Suite needs at least one top-level test_*.py file.")
    write_files(destination, {name: content.encode() for name, content in files.items()})
    return FrozenSuite(suite_hash=fingerprint(files), files=files)
