#!/usr/bin/env python3
"""Render clash/Merge.yaml template with private env values.

Usage:
    python3 scripts/render-clash-merge.py [--dry-run] [--check]

Reads private/clash/Merge.env (key=value, multi-line via indent),
substitutes {{PLACEHOLDERS}} in proxy/clash/Merge.yaml.
"""
import argparse
import os
import re
import sys


def find_repo_root() -> str:
    """Find the template repo root (parent of scripts/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_env(path: str) -> dict[str, str]:
    """Parse a .env file with multi-line values (indented continuation lines).

    Format:
        KEY=value
        MULTI_KEY=
          line1
          line2
    """
    env: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")

            # Skip empty lines and comments
            if not line or line.lstrip().startswith("#"):
                continue

            # New key=value line
            match = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)", line)
            if match:
                # Save previous multi-line key
                if current_key is not None:
                    env[current_key] = "\n".join(current_lines)

                current_key = match.group(1)
                value = match.group(2)

                if value == "":
                    # Multi-line value starts on next lines
                    current_lines = []
                else:
                    # Single-line value
                    env[current_key] = value
                    current_key = None
                    current_lines = []
            elif current_key is not None and line.startswith("  "):
                # Continuation line: keep indentation for YAML structure
                current_lines.append(line)

    # Save last multi-line key
    if current_key is not None:
        env[current_key] = "\n".join(current_lines)

    return env


def render_template(template_path: str, env: dict[str, str]) -> str:
    """Replace {{PLACEHOLDERS}} in template with env values."""
    with open(template_path) as f:
        content = f.read()

    def replacer(match: re.Match) -> str:
        key = match.group(1)
        if key in env:
            return env[key]
        # Leave unresolved placeholders as-is (with warning marker)
        return match.group(0)

    return re.sub(r"\{\{([A-Z_][A-Z0-9_]*)\}\}", replacer, content)


def check_unresolved(content: str) -> list[str]:
    """Return list of unresolved {{PLACEHOLDERS}}."""
    return re.findall(r"\{\{([A-Z_][A-Z0-9_]*)\}\}", content)


def main():
    parser = argparse.ArgumentParser(description="Render Clash Merge.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Print rendered output without writing")
    parser.add_argument("--check", action="store_true", help="Check for unresolved placeholders only")
    args = parser.parse_args()

    repo_root = find_repo_root()
    template_path = os.path.join(repo_root, "proxy", "clash", "Merge.yaml")
    env_path = os.path.join(repo_root, "..", "private", "clash", "Merge.env")
    output_path = os.path.expanduser(
        "~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles/Merge.yaml"
    )

    # Fallback: check MAC_BOOTSTRAP_PRIVATE_DIR
    private_dir = os.environ.get("MAC_BOOTSTRAP_PRIVATE_DIR", "")
    if private_dir and not os.path.exists(env_path):
        env_path = os.path.join(private_dir, "clash", "Merge.env")

    if not os.path.exists(template_path):
        print(f"ERROR: template not found: {template_path}", file=sys.stderr)
        return 1

    if not os.path.exists(env_path):
        print(f"ERROR: private env not found: {env_path}", file=sys.stderr)
        return 1

    env = parse_env(env_path)
    rendered = render_template(template_path, env)
    unresolved = check_unresolved(rendered)

    if args.check:
        if unresolved:
            print(f"Unresolved placeholders: {unresolved}")
            return 1
        print("OK: all placeholders resolved")
        return 0

    if unresolved:
        print(f"WARNING: unresolved placeholders: {unresolved}", file=sys.stderr)

    if args.dry_run:
        print(rendered)
        return 0

    with open(output_path, "w") as f:
        f.write(rendered)
    print(f"  proxy/clash/Merge.yaml <- private/clash/Merge.env ({len(env)} keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
