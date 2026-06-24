"""Build and query the local agent prompt-library index."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


BOOTSTRAP = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = BOOTSTRAP / "agent" / "prompts" / "sources.json"
HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$")


def expand(path: str) -> Path:
    return Path(path).expanduser()


def agent_home() -> Path:
    return expand(os.environ.get("AGENT_HOME", "~/.agent"))


def load_sources(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def prompt_root(config: dict[str, Any]) -> Path:
    if "AGENT_PROMPTS_HOME" in os.environ:
        return expand(os.environ["AGENT_PROMPTS_HOME"])
    if "AGENT_HOME" in os.environ:
        return expand(os.environ["AGENT_HOME"]) / "prompts"
    default = config.get("prompt_root", "~/.agent/prompts")
    return expand(default)


def upstream_root() -> Path:
    return expand(os.environ.get("AGENT_UPSTREAM_HOME", str(agent_home() / "upstream")))


def index_path(config: dict[str, Any]) -> Path:
    if "AGENT_PROMPT_INDEX" in os.environ:
        return expand(os.environ["AGENT_PROMPT_INDEX"])
    if "AGENT_HOME" in os.environ:
        return expand(os.environ["AGENT_HOME"]) / "prompts" / "index.json"
    root = prompt_root(config)
    default = config.get("index_file", str(root / "index.json"))
    return expand(default)


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[`*_~\[\](){}<>\"']", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[:：/\\|]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
        return f"prompt-{digest}"
    return text[:120]


def preview(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact[:limit]


def rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fabric_records(source_id: str, cfg: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    patterns = root / cfg.get("patterns_path", "data/patterns")
    if not patterns.is_dir():
        return []

    records: list[dict[str, Any]] = []
    for pattern_dir in sorted(p for p in patterns.iterdir() if p.is_dir()):
        files = []
        preview_text = ""
        for role, name in (("system", "system.md"), ("user", "user.md"), ("readme", "README.md")):
            path = pattern_dir / name
            if path.is_file():
                files.append({"role": role, "path": rel(path, root)})
                if not preview_text and role in {"system", "user"}:
                    preview_text = read_text(path)
        if not files:
            continue
        name = pattern_dir.name
        records.append(
            {
                "id": f"{source_id}:{name}",
                "source": source_id,
                "title": name,
                "format": "fabric-pattern",
                "entrypoint": rel(pattern_dir, root),
                "files": files,
                "license": cfg.get("license", ""),
                "repo": cfg.get("repo", ""),
                "preview": preview(preview_text),
            }
        )
    return records


def iter_markdown_files(root: Path, patterns: list[str]) -> list[Path]:
    matches: list[Path] = []
    for path in root.rglob("*.md"):
        rel_path = rel(path, root)
        if any(fnmatch.fnmatch(rel_path, pattern) for pattern in patterns):
            matches.append(path)
    return sorted(matches)


def section_ranges(lines: list[str]) -> list[tuple[int, int, int, str]]:
    headings: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            headings.append((idx, len(match.group(1)), match.group(2).strip()))

    ranges: list[tuple[int, int, int, str]] = []
    for current, (start, level, title) in enumerate(headings):
        end = len(lines)
        for next_start, next_level, _ in headings[current + 1 :]:
            if next_level <= level:
                end = next_start
                break
        ranges.append((start, end, level, title))
    return ranges


def markdown_records(source_id: str, cfg: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    patterns = cfg.get("files", ["README.md"])
    min_chars = int(cfg.get("min_section_chars", 80))
    records: list[dict[str, Any]] = []
    seen: dict[str, int] = {}

    for path in iter_markdown_files(root, patterns):
        lines = read_text(path).splitlines()
        for start, end, level, title in section_ranges(lines):
            body = "\n".join(lines[start:end]).strip()
            if len(body) < min_chars:
                continue
            base_slug = slugify(title)
            seen[base_slug] = seen.get(base_slug, 0) + 1
            slug = base_slug if seen[base_slug] == 1 else f"{base_slug}-{seen[base_slug]}"
            records.append(
                {
                    "id": f"{source_id}:{slug}",
                    "source": source_id,
                    "title": title,
                    "format": "markdown-section",
                    "source_file": rel(path, root),
                    "start_line": start + 1,
                    "end_line": end,
                    "heading_level": level,
                    "license": cfg.get("license", ""),
                    "repo": cfg.get("repo", ""),
                    "preview": preview(body),
                }
            )
    return records


def build_index(config: dict[str, Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    upstream = upstream_root()

    for source_id, cfg in sorted(config.get("sources", {}).items()):
        root = upstream / cfg["upstream_dir"]
        if not root.exists():
            issues.append({"source": source_id, "issue": f"missing upstream: {root}"})
            continue
        mode = cfg.get("mode")
        if mode == "fabric-patterns":
            source_records = fabric_records(source_id, cfg, root)
        elif mode == "markdown-sections":
            source_records = markdown_records(source_id, cfg, root)
        else:
            issues.append({"source": source_id, "issue": f"unknown mode: {mode}"})
            continue
        if not source_records:
            issues.append({"source": source_id, "issue": "no prompt records found"})
        records.extend(source_records)

    return {
        "version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "upstream_root": str(upstream),
        "prompt_root": str(prompt_root(config)),
        "sources": config.get("sources", {}),
        "prompts": records,
        "issues": issues,
    }


def write_index(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_index(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"Missing prompt index: {path}\nRun: make prompt-sync")
    return json.loads(path.read_text(encoding="utf-8"))


def source_root(index: dict[str, Any], record: dict[str, Any]) -> Path:
    cfg = index["sources"][record["source"]]
    return Path(index["upstream_root"]) / cfg["upstream_dir"]


def record_matches(record: dict[str, Any], query: str) -> bool:
    haystack = " ".join(
        str(record.get(key, "")) for key in ("id", "title", "source", "format", "preview")
    ).lower()
    return query.lower() in haystack


def find_record(index: dict[str, Any], key: str) -> dict[str, Any]:
    prompts = index.get("prompts", [])
    for record in prompts:
        if record["id"] == key:
            return record

    matches = [
        record
        for record in prompts
        if key.lower() in record["id"].lower() or key.lower() in record["title"].lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"No prompt matched: {key}")

    print(f"Multiple prompts matched: {key}", file=sys.stderr)
    for record in matches[:20]:
        print(f"  {record['id']}  {record['title']}", file=sys.stderr)
    raise SystemExit(2)


def show_record(index: dict[str, Any], record: dict[str, Any]) -> str:
    root = source_root(index, record)
    if record["format"] == "fabric-pattern":
        chunks = [f"# {record['title']}"]
        for item in record.get("files", []):
            if item["role"] not in {"system", "user"}:
                continue
            path = root / item["path"]
            chunks.append(f"\n## {item['role']}\n\n{read_text(path).strip()}")
        return "\n".join(chunks).rstrip() + "\n"

    if record["format"] == "markdown-section":
        path = root / record["source_file"]
        lines = read_text(path).splitlines()
        start = int(record["start_line"]) - 1
        end = int(record["end_line"])
        return "\n".join(lines[start:end]).rstrip() + "\n"

    raise SystemExit(f"Unsupported prompt format: {record['format']}")


def cmd_build(args: argparse.Namespace) -> int:
    config = load_sources(args.sources)
    data = build_index(config)
    target = args.output or index_path(config)
    write_index(data, target)
    print(f"indexed {len(data['prompts'])} prompts -> {target}")
    if data["issues"]:
        print("issues:")
        for issue in data["issues"]:
            print(f"  {issue['source']}: {issue['issue']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config = load_sources(args.sources)
    data = load_index(args.index or index_path(config))
    query = " ".join(args.query).strip()
    prompts = data.get("prompts", [])
    if query:
        prompts = [record for record in prompts if record_matches(record, query)]
    for record in prompts[: args.limit]:
        print(f"{record['id']}\t{record['title']}\t{record['format']}")
    if len(prompts) > args.limit:
        print(f"... {len(prompts) - args.limit} more")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    config = load_sources(args.sources)
    data = load_index(args.index or index_path(config))
    record = find_record(data, args.prompt_id)
    sys.stdout.write(show_record(data, record))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_sources(args.sources)
    data = load_index(args.index or index_path(config))
    counts: dict[str, int] = {}
    for record in data.get("prompts", []):
        counts[record["source"]] = counts.get(record["source"], 0) + 1
    for source_id in sorted(config.get("sources", {})):
        print(f"{source_id}: {counts.get(source_id, 0)} prompts")
    if data.get("issues"):
        print("issues:")
        for issue in data["issues"]:
            print(f"  {issue['source']}: {issue['issue']}")
        return 1
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    root.add_argument("--index", type=Path, default=None)
    sub = root.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build prompt index from local upstream repos")
    build.add_argument("--output", type=Path, default=None)
    build.set_defaults(func=cmd_build)

    list_cmd = sub.add_parser("list", help="list prompt records")
    list_cmd.add_argument("query", nargs="*")
    list_cmd.add_argument("--limit", type=int, default=80)
    list_cmd.set_defaults(func=cmd_list)

    search = sub.add_parser("search", help="search prompt records")
    search.add_argument("query", nargs="*")
    search.add_argument("--limit", type=int, default=80)
    search.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="print one prompt by id or unique title match")
    show.add_argument("prompt_id")
    show.set_defaults(func=cmd_show)

    doctor = sub.add_parser("doctor", help="validate the current prompt index")
    doctor.set_defaults(func=cmd_doctor)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
