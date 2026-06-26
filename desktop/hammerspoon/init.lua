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
local shottr_app = "/Applications/Shottr.app/Contents/MacOS/Shottr"
local shottr_bundle_id = "cc.ffitch.shottr"

local function ensure_dir(path)
  os.execute("mkdir -p " .. string.format("%q", path))
end

hs.grid.setGrid("3x2")

require("wuying")

local clipboard_tool = hs.loadSpoon("ClipboardTool")
if clipboard_tool then
  spoon.ClipboardTool.hist_size = 80
  spoon.ClipboardTool.show_copied_alert = false
  spoon.ClipboardTool:bindHotkeys({
    show_clipboard = { hyper, "V" },
  })
  spoon.ClipboardTool:start()
else
  hs.alert.show("ClipboardTool spoon missing")
end

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

hs.hotkey.bind(hyper, "S", function()
  hs.task.new(shottr_app, nil, {}):start()
  hs.alert.show("Shottr launched")
end)

local function run_shottr_action(url, message, attempt)
  local shottr = hs.application.get(shottr_bundle_id)
  local current_attempt = attempt or 1

  if shottr then
    hs.urlevent.openURL(url)
    hs.alert.show(message)
    return
  end

  if current_attempt == 1 then
    hs.task.new(shottr_app, nil, {}):start()
  end

  if current_attempt >= 8 then
    hs.alert.show("Shottr not ready")
    return
  end

  hs.timer.doAfter(0.2, function()
    run_shottr_action(url, message, current_attempt + 1)
  end)
end

hs.hotkey.bind(hyper, "E", function()
  run_shottr_action("shottr://grab/area?then=edit", "Shottr: edit")
end)

hs.hotkey.bind(hyper, "C", function()
  run_shottr_action("shottr://grab/area?then=copy", "Shottr: copy")
end)

hs.hotkey.bind(hyper, "P", function()
  run_shottr_action("shottr://grab/area?then=pin", "Shottr: pin")
end)

hs.hotkey.bind(hyper, "O", function()
  run_shottr_action("shottr://ocr", "Shottr: ocr")
end)

hs.hotkey.bind(hyper, "U", function()
  run_shottr_action("shottr://grab/scrolling?then=pin", "Shottr: scrolling")
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
