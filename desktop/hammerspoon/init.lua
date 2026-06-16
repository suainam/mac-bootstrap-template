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

local function ensure_dir(path)
  os.execute("mkdir -p " .. string.format("%q", path))
end

hs.grid.setGrid("3x2")

-- === Auto-switch input method by app ===
local en = "com.apple.keylayout.ABC"
local zh = "com.bytedance.inputmethod.doubaoime.pinyin"

local log_file = os.getenv("HOME") .. "/.hammerspoon/wuying.log"
local function log(msg)
  local f = io.open(log_file, "a")
  if f then
    f:write(os.date("%Y-%m-%d %H:%M:%S") .. " " .. msg .. "\n")
    f:close()
  end
end

local function press_escape_then_win(app)
  log("press_escape_then_win called, app=" .. tostring(app))
  hs.timer.doAfter(0.5, function()
    hs.eventtap.event.newKeyEvent(hs.keycodes.map.escape, true):post(app)
    hs.eventtap.event.newKeyEvent(hs.keycodes.map.escape, false):post(app)
    hs.timer.doAfter(0.2, function()
      hs.eventtap.event.newKeyEvent(hs.keycodes.map.cmd, true):post(app)
      hs.eventtap.event.newKeyEvent(hs.keycodes.map.cmd, false):post(app)
      hs.timer.doAfter(0.2, function()
        hs.eventtap.event.newKeyEvent(hs.keycodes.map.cmd, true):post(app)
        hs.eventtap.event.newKeyEvent(hs.keycodes.map.cmd, false):post(app)
        log("press_escape_then_win done")
      end)
    end)
  end)
end

local wuying_bids = {
  ["com.aliyun.wuying.osx"] = true,
  ["com.aliyun.wuying.viewer"] = true,
}

local en_apps = {}
local zh_apps = {
  ["com.microsoft.VSCode"] = true,
}
local zh_app_names = {
  ["iTerm2"] = true,
  ["Ghostty"] = true,
}

local function is_wuying(bid)
  local result = wuying_bids[bid] or bid:find("com.aliyun.wuying.", 1, true)
  if result then
    log("wuying detected: " .. bid)
  end
  return result
end

local in_wuying = false
local function on_wuying_enter()
  log("on_wuying_enter called, in_wuying=" .. tostring(in_wuying))
  if in_wuying then return end
  in_wuying = true
  hs.keycodes.currentSourceID(en)
  -- Get wuying app object and pass to press_escape_then_win
  local wuying_app = hs.application.get("com.aliyun.wuying.viewer") or hs.application.get("com.aliyun.wuying.osx")
  log("wuying_app=" .. tostring(wuying_app))
  if wuying_app then
    press_escape_then_win(wuying_app)
  else
    log("ERROR: wuying app not found")
  end
  -- Reset flag after 2s as safety net
  hs.timer.doAfter(2, function()
    log("2s reset: in_wuying was " .. tostring(in_wuying))
    in_wuying = false
  end)
end

local input_watcher = hs.application.watcher.new(function(app_name, event, app)
  log("event=" .. tostring(event) .. " app=" .. tostring(app_name) .. " bid=" .. tostring(app and app:bundleID()))

  if event == hs.application.watcher.deactivated then
    hs.timer.doAfter(0.05, function()
      local front = hs.application.frontmostApplication()
      if not front then return end
      local bid = front:bundleID()
      log("deactivated check: bid=" .. tostring(bid) .. " in_wuying=" .. tostring(in_wuying))
      if bid and is_wuying(bid) then
        on_wuying_enter()
      else
        in_wuying = false
      end
    end)
    return
  end

  if event ~= hs.application.watcher.activated then return end
  if not app then return end
  local bid = app:bundleID()
  if not bid then return end

  if is_wuying(bid) then
    on_wuying_enter()
  elseif en_apps[bid] then
    in_wuying = false
    hs.keycodes.currentSourceID(en)
  elseif zh_apps[bid] or zh_app_names[app_name] then
    in_wuying = false
    hs.keycodes.currentSourceID(zh)
  else
    in_wuying = false
  end
end)
input_watcher:start()

-- Safety net: reset in_wuying flag every 3s if wuying is not frontmost
hs.timer.doEvery(3, function()
  local front = hs.application.frontmostApplication()
  if not front then return end
  local bid = front:bundleID()
  log("3s timer: bid=" .. tostring(bid) .. " in_wuying=" .. tostring(in_wuying))
  if not (bid and is_wuying(bid)) then
    in_wuying = false
  end
end)

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

local function launch_shottr_then_open(url)
  hs.task.new(shottr_app, nil, {}):start()
  hs.timer.doAfter(0.7, function()
    hs.execute(string.format("open %q", url))
  end)
end

hs.hotkey.bind(hyper, "E", function()
  local path = "/tmp/shottr-edit.png"
  hs.task.new("/usr/sbin/screencapture", function(exitCode)
    if exitCode == 0 then
      hs.execute(string.format("open -a Shottr %q", path))
      hs.alert.show("Shottr: edit")
    end
  end, {"-i", path}):start()
end)

hs.hotkey.bind(hyper, "C", function()
  hs.task.new("/usr/sbin/screencapture", nil, {"-i", "-c"}):start()
end)

hs.hotkey.bind(hyper, "P", function()
  hs.task.new("/usr/sbin/screencapture", function(exitCode)
    if exitCode == 0 then
      hs.task.new(shottr_app, nil, {}):start()
      hs.timer.doAfter(0.7, function()
        hs.execute("open 'shottr://load/clipboard'")
        hs.timer.doAfter(0.5, function()
          hs.osascript.applescript([[
            tell application id "cc.ffitch.shottr"
              activate
            end tell
            delay 0.2
            tell application "System Events"
              tell process "Shottr"
                click menu item "Pin to Screen" of menu 1 of menu bar item "File" of menu bar 1
              end tell
            end tell
          ]])
        end)
      end)
      hs.alert.show("Shottr: pin")
    end
  end, {"-i", "-c"}):start()
end)

hs.hotkey.bind(hyper, "O", function()
  hs.task.new(shottr_app, nil, {}):start()
  hs.timer.doAfter(0.7, function()
    hs.execute("open 'shottr://ocr'")
  end)
  hs.alert.show("Shottr: ocr")
end)

hs.hotkey.bind(hyper, "U", function()
  hs.task.new(shottr_app, nil, {}):start()
  hs.timer.doAfter(0.7, function()
    hs.execute("open 'shottr://grab/scrolling?then=pin'")
  end)
  hs.alert.show("Shottr: scrolling")
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
