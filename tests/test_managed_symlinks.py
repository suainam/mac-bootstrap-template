"""Managed symlink health checks."""

import os

import pytest

from helpers import TEMPLATE, managed_symlinks


@pytest.mark.parametrize("path", managed_symlinks().keys())
def test_symlink_not_broken(path):
    expanded = os.path.expanduser(path)
    assert os.path.islink(expanded), f"{path} is not a symlink"
    assert os.path.exists(expanded), f"{path} is a broken symlink"


@pytest.mark.parametrize("path,target", managed_symlinks().items())
def test_symlink_points_to_current_target(path, target):
    assert os.path.realpath(os.path.expanduser(path)) == os.path.join(TEMPLATE, target)
