-- === Wuying Auto-Keystroke ===
-- Automatically sends Escape and Command (Win) key when Wuying becomes active.
-- This helps initialize the Wuying desktop state.

local log_file = os.getenv("HOME") .. "/.hammerspoon/wuying.log"
local function log(msg)
  local f = io.open(log_file, "a")
  if f then
    f:write(os.date("%Y-%m-%d %H:%M:%S") .. " " .. msg .. "\n")
    f:close()
  end
end

-- Keep references to timers to prevent them from being garbage collected before firing
local wuying_timers = {}

local function press_escape_then_win()
  log("press_escape_then_win called")
  wuying_timers.t1 = hs.timer.doAfter(0.5, function()
    -- Send globally (to frontmost) because Wuying ignores PID-targeted events.
    hs.eventtap.keyStroke({}, "escape", 0)
    wuying_timers.t2 = hs.timer.doAfter(0.2, function()
      hs.eventtap.event.newKeyEvent(hs.keycodes.map.cmd, true):post()
      hs.eventtap.event.newKeyEvent(hs.keycodes.map.cmd, false):post()
      wuying_timers.t3 = hs.timer.doAfter(0.2, function()
        hs.eventtap.event.newKeyEvent(hs.keycodes.map.cmd, true):post()
        hs.eventtap.event.newKeyEvent(hs.keycodes.map.cmd, false):post()
        log("press_escape_then_win done")
      end)
    end)
  end)
end

local wuying_bids = {
  ["com.aliyun.wuying.osx"] = true,
  ["com.aliyun.wuying.viewer"] = true,
}

local function is_wuying(bid)
  return bid and (wuying_bids[bid] or bid:find("com.aliyun.wuying.", 1, true))
end

local in_wuying = false
local wuying_probe_token = 0
local wuying_probe_delays = { 0.05, 0.15, 0.35, 0.7 }

local function on_wuying_enter(app)
  log("on_wuying_enter called, in_wuying=" .. tostring(in_wuying))
  if in_wuying then return end
  in_wuying = true
  wuying_probe_token = wuying_probe_token + 1
  
  if app then
    app:activate()
  end
  press_escape_then_win()
  
  wuying_timers.reset = hs.timer.doAfter(2, function()
    log("2s reset: in_wuying was " .. tostring(in_wuying))
    in_wuying = false
  end)
end

local function probe_frontmost_for_wuying(reason)
  wuying_probe_token = wuying_probe_token + 1
  local probe_id = wuying_probe_token
  for idx, delay in ipairs(wuying_probe_delays) do
    wuying_timers["probe" .. idx] = hs.timer.doAfter(delay, function()
      if probe_id ~= wuying_probe_token or in_wuying then return end
      local front = hs.application.frontmostApplication()
      local bid = front and front:bundleID()
      log("probe reason=" .. reason .. " delay=" .. tostring(delay) .. " bid=" .. tostring(bid))
      if is_wuying(bid) then
        on_wuying_enter(front)
      elseif idx == #wuying_probe_delays then
        in_wuying = false
      end
    end)
  end
end

-- Ensure watcher is assigned to global namespace so it isn't garbage collected
_G.wuying_watcher = hs.application.watcher.new(function(app_name, event, app)
  if event == hs.application.watcher.deactivated then
    probe_frontmost_for_wuying("deactivated:" .. tostring(app_name))
    return
  end

  if event == hs.application.watcher.activated then
    local bid = app and app:bundleID()
    if is_wuying(bid) then
      on_wuying_enter(app)
    else
      in_wuying = false
    end
  end
end)
_G.wuying_watcher:start()
