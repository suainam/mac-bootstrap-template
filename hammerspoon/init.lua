-- Hammerspoon = OS tier only.
-- zj / zellij = terminal tier only.
-- Keep the boundary clean:
-- - Hammerspoon owns global hotkeys, window placement, clipboard helpers.
-- - zj owns pane/tab keys inside the terminal.
-- - No shared prefix with zj. Use Hyper for system actions.

local hyper = { "cmd", "alt", "ctrl" }
local terminal_app = "iTerm2"
local clipboard_dir = os.getenv("HOME") .. "/Pictures/ClipboardShots"
local shottr_scheme = "shottr://grab/fullscreen?then=%s"
local shottr_app = "/Applications/Shottr.app/Contents/MacOS/Shottr"

local function ensure_dir(path)
  os.execute("mkdir -p " .. string.format("%q", path))
end

hs.grid.setGrid("3x2")

local clipboard_tool = hs.loadSpoon("ClipboardTool")
if clipboard_tool then
  spoon.ClipboardTool.hist_size = 80
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
  hs.grid.show()
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
  hs.application.launchOrFocus(terminal_app)
  hs.timer.doAfter(0.4, function()
    hs.osascript.applescript([[
      tell application "iTerm2"
        activate
        tell current session of current window to write text "zj"
      end tell
    ]])
  end)
end)

hs.hotkey.bind(hyper, "S", function()
  hs.task.new(shottr_app, nil, {}):start()
  hs.alert.show("Shottr launched")
end)

local function launch_shottr_then_open(url)
  hs.task.new(shottr_app, nil, {}):start()
  hs.timer.doAfter(0.7, function()
    hs.execute(string.format("open %q", url))
  end)
end

local function open_shottr_action(action)
  local url = string.format(shottr_scheme, action)
  launch_shottr_then_open(url)
  hs.alert.show("Shottr: " .. action)
end

hs.hotkey.bind(hyper, "E", function()
  open_shottr_action("edit")
end)

hs.hotkey.bind(hyper, "C", function()
  open_shottr_action("copy")
end)

hs.hotkey.bind(hyper, "P", function()
  open_shottr_action("pin")
end)

hs.hotkey.bind(hyper, "O", function()
  launch_shottr_then_open("shottr://settings")
  hs.alert.show("Shottr settings")
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
