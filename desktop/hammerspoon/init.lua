-- Hammerspoon = OS tier only.
-- tmux = terminal tier only.
-- Keep the boundary clean:
-- - Hammerspoon owns global hotkeys, window placement, clipboard helpers.
-- - tmux owns pane/tab keys inside the terminal.
-- - No shared prefix with tmux. Use Hyper for system actions.

local hyper = { "cmd", "alt", "ctrl" }
local iterm2_bundle_id = "com.googlecode.iterm2"
local ghostty_bundle_id = "com.mitchellh.ghostty"
local clipboard_dir = os.getenv("HOME") .. "/Pictures/ClipboardShots"

local function ensure_dir(path)
  os.execute("mkdir -p " .. string.format("%q", path))
end

hs.grid.setGrid("3x2")

require("wuying")
local keybindings_tool = hs.loadSpoon("HSKeybindings")
local keybindings_visible = false

hs.hotkey.bind(hyper, "R", function()
  hs.reload()
end)

hs.hotkey.bind(hyper, "G", function()
  hs.application.launchOrFocusByBundleID(ghostty_bundle_id)
end)

hs.hotkey.bind(hyper, "K", function()
  if keybindings_tool then
    if keybindings_visible then
      spoon.HSKeybindings:hide()
      keybindings_visible = false
    else
      spoon.HSKeybindings:show()
      keybindings_visible = true
    end
  else
    hs.alert.show("HSKeybindings spoon missing")
  end
end)

hs.hotkey.bind({ "ctrl", "shift" }, "V", function()
  local img = hs.pasteboard.readImage()
  if not img then
    hs.alert.show("No image in clipboard")
    return
  end

  ensure_dir(clipboard_dir)
  local filename = os.date("ai-shot-%Y%m%d-%H%M%S.png")
  local path = clipboard_dir .. "/" .. filename
  if img:saveToFile(path) then
    hs.alert.show("Saved: " .. filename)
  else
    hs.alert.show("Save failed")
  end
end)

hs.hotkey.bind(hyper, "T", function()
  hs.application.launchOrFocusByBundleID(iterm2_bundle_id)
end)

hs.hotkey.bind(hyper, "Left", function()
  local win = hs.window.focusedWindow()
  if win then win:moveToUnit(hs.layout.left50) end
end)

hs.hotkey.bind(hyper, "Right", function()
  local win = hs.window.focusedWindow()
  if win then win:moveToUnit(hs.layout.right50) end
end)

hs.hotkey.bind(hyper, "Up", function()
  local win = hs.window.focusedWindow()
  if win then win:maximize() end
end)

hs.hotkey.bind(hyper, "Down", function()
  local win = hs.window.focusedWindow()
  if win then win:moveToUnit(hs.layout.left50) end
end)
