"""Desktop automation checks."""

import os

import pytest

from helpers import TEMPLATE


pytestmark = pytest.mark.machine


# ── Hammerspoon ───────────────────────────────────────────────────────

def test_hammerspoon_has_ghostty_binding():
    content = open(os.path.expanduser("~/.hammerspoon/init.lua")).read()
    assert "ghostty_bundle_id" in content


def test_hammerspoon_has_iterm2_binding():
    content = open(os.path.expanduser("~/.hammerspoon/init.lua")).read()
    assert "iterm2_bundle_id" in content


# ── Hammerspoon Spoons ────────────────────────────────────────────────

def test_spoons_installed():
    spoons = os.listdir(os.path.expanduser("~/.hammerspoon/Spoons"))
    assert "ClipboardTool.spoon" in spoons
    assert "HSKeybindings.spoon" in spoons
