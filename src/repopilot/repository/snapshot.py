import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import CodeExcerpt, Issue, RepositoryContext

EXCLUDED = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    "planning",
    ".repopilot",
    "__pycache__",
    "vendor",
    "site-packages",
}
TEXT_SUFFIXES = {".py", ".toml", ".ini", ".cfg", ".md", ".rst", ".txt", ".yaml", ".yml"}
MAX_FILE_BYTES = 64_000
MAX_SCAN_BYTES = 2_000_000
MAX_SCAN_FILES = 120
MAX_CONTEXT_CHARS = 30_000


def _git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            input=input_bytes,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RepoPilotError(
            "git_unavailable", "Git could not read the requested snapshot."
        ) from error
    if result.returncode:
        raise RepoPilotError("git_read_failed", "Git could not read the requested repository/ref.")
    if len(result.stdout) > 12_000_000:
        raise RepoPilotError("repository_too_large", "Git snapshot metadata exceeds the limit.")
    return result.stdout


def _terms(issue: Issue) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", issue.title + " " + issue.body)
    words += [part for word in words for part in re.split(r"_|(?<=[a-z])(?=[A-Z])", word)]
    stop = {"the", "and", "for", "that", "this", "with", "from", "have", "not", "issue", "should"}
    return {word.casefold() for word in words if len(word) > 2 and word.casefold() not in stop}


def _origin_slug(root: Path) -> str | None:
    try:
        raw = _git(root, "config", "--get", "remote.origin.url").decode().strip()
    except RepoPilotError:
        return None
    if raw.startswith("git@github.com:"):
        return raw.removeprefix("git@github.com:").removesuffix(".git").strip("/")
    parsed = urlsplit(raw)
    if parsed.hostname == "github.com":
        return parsed.path.strip("/").removesuffix(".git")
    return None


def inspect_repository(root: Path, issue: Issue, ref: str = "HEAD") -> RepositoryContext:
    root = root.resolve()
    if not root.is_dir():
        raise RepoPilotError("repository_missing", "The local repository directory does not exist.")
    _git(root, "rev-parse", "--show-toplevel")
    commit = (
        _git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
    )
    tree_oid = _git(root, "rev-parse", "--verify", commit + "^{tree}").decode().strip()
    origin = _origin_slug(root)
    if origin and issue.repository and origin.casefold() != issue.repository.casefold():
        raise RepoPilotError("repository_mismatch", "Issue repository and local origin disagree.")
    limitations = [
        "Reads only tracked files at base_commit; uncommitted and untracked files are excluded.",
        "No target code, installation command, or test has been executed.",
        "Retrieval is bounded; relevant files may be outside the selected context.",
    ]
    if not origin:
        limitations.append("The local repository origin could not be matched to the Issue.")
    entries = []
    for record in _git(root, "ls-tree", "-r", "-l", "-z", "--full-tree", commit).split(b"\0"):
        if not record:
            continue
        meta, raw_path = record.split(b"\t", 1)
        mode, kind, oid, size = meta.decode("ascii").split()
        path = raw_path.decode("utf-8", errors="strict")
        entries.append((mode, kind, oid, size, path))
    digest = hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()
    terms = _terms(issue)
    regular = [entry for entry in entries if entry[0] in {"100644", "100755"}]
    candidates = []
    for _mode, _kind, oid, size, path in regular:
        parts = PurePosixPath(path).parts
        if (
            set(parts) & EXCLUDED
            or any(part.startswith(".env") for part in parts)
            or PurePosixPath(path).suffix.lower() not in TEXT_SUFFIXES
            or int(size) > MAX_FILE_BYTES
        ):
            continue
        path_score = sum(8 for term in terms if term in path.casefold())
        candidates.append((path_score, path, oid, int(size)))
    candidates.sort(key=lambda entry: (-entry[0], entry[1]))
    selected = []
    total_bytes = 0
    for entry in candidates:
        if len(selected) == MAX_SCAN_FILES or total_bytes + entry[3] > MAX_SCAN_BYTES:
            break
        selected.append(entry)
        total_bytes += entry[3]
    if not selected or not any(entry[1].endswith(".py") for entry in selected):
        raise RepoPilotError("unsupported_repository", "No Python source fits the snapshot limits.")
    raw_blobs = _git(
        root,
        "cat-file",
        "--batch",
        input_bytes="".join(entry[2] + "\n" for entry in selected).encode("ascii"),
    )
    offset = 0
    ranked = []
    for path_score, path, expected_oid, expected_size in selected:
        end = raw_blobs.index(b"\n", offset)
        oid, kind, size = raw_blobs[offset:end].decode("ascii").split()
        size = int(size)
        if oid != expected_oid or kind != "blob" or size != expected_size:
            raise RepoPilotError("snapshot_invalid", "Git blob did not match the pinned tree.")
        content = raw_blobs[end + 1 : end + 1 + size]
        offset = end + size + 2
        if b"\0" in content:
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        lines = text.splitlines()
        if not lines:
            continue
        hits = [sum(1 for term in terms if term in line.casefold()) for line in lines]
        center = max(range(len(lines)), key=lambda index: hits[index])
        first = 0 if len(lines) <= 160 else max(0, center - 20)
        last = len(lines) if len(lines) <= 160 else min(len(lines), first + 80)
        symbols = []
        if path.endswith(".py"):
            try:
                symbols = [
                    node.name
                    for node in ast.walk(ast.parse(text))
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                ][:40]
            except (SyntaxError, ValueError, RecursionError):
                limitations.append(f"Could not parse Python symbols for {path}.")
        score = path_score + sum(min(hit, 4) for hit in hits)
        ranked.append(
            CodeExcerpt(
                path=path,
                blob_oid=expected_oid,
                start_line=first + 1,
                end_line=last,
                content="\n".join(lines[first:last]),
                symbols=symbols,
                retrieval_score=score,
            )
        )
    ranked.sort(key=lambda entry: (-entry.retrieval_score, entry.path))
    excerpts = []
    characters = 0
    for excerpt in ranked:
        if len(excerpts) == 8:
            break
        if characters + len(excerpt.content) > MAX_CONTEXT_CHARS:
            continue
        excerpts.append(excerpt)
        characters += len(excerpt.content)
    if not excerpts:
        raise RepoPilotError("empty_context", "No readable source excerpt fits the context budget.")
    has_tests = any(
        path.startswith("tests/") or path.endswith("pytest.ini") for *_, path in regular
    )
    return RepositoryContext(
        base_commit=commit,
        tree_oid=tree_oid,
        tree_manifest_sha256=digest,
        total_regular_files=len(regular),
        scanned_files=len(selected),
        excerpts=excerpts,
        candidate_test_commands=[["python", "-m", "pytest"]] if has_tests else [],
        limitations=limitations,
    )
