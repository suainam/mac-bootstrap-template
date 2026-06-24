"""Obsidian kit and code-server infrastructure checks."""

import os

from helpers import TEMPLATE


def test_obsidian_vault_kit_exists():
    root = os.path.join(TEMPLATE, "editors", "obsidian")
    assert os.path.exists(os.path.join(root, "install.sh"))
    assert os.path.exists(os.path.join(root, "vault", ".obsidian", "daily-notes.json"))
    assert os.path.exists(os.path.join(root, "vault", "docs", "templates", "weekly.md"))

# ── code-server infra ─────────────────────────────────────────────────

def test_code_server_dockerfile_exists():
    path = os.path.join(TEMPLATE, "infra", "code-server", "Dockerfile")
    assert os.path.exists(path)


def test_code_server_docker_compose_exists():
    path = os.path.join(TEMPLATE, "infra", "code-server", "docker-compose.yml")
    assert os.path.exists(path)


def test_code_server_dockerfile_has_docker_cli():
    content = open(os.path.join(TEMPLATE, "infra", "code-server", "Dockerfile")).read()
    assert "docker-ce-cli" in content
    assert "docker-compose-plugin" in content


def test_code_server_compose_mounts_docker_sock():
    content = open(os.path.join(TEMPLATE, "infra", "code-server", "docker-compose.yml")).read()
    assert "/var/run/docker.sock" in content


def test_code_server_paths_are_parameterized():
    install = open(os.path.join(TEMPLATE, "infra", "code-server", "install.sh")).read()
    compose = open(os.path.join(TEMPLATE, "infra", "code-server", "docker-compose.yml")).read()
    assert 'CODE_SERVER_DIR:-/srv/code-server' in install
    assert '${CODE_SERVER_WORKSPACE_DIR:-/workspace}:/root/dev' in compose
