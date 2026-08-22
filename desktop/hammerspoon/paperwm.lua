-- PaperWM.spoon scrollable tiling window manager integration.
-- Provides infinite horizontal ribbon / scrollable tiling layout.

local paperwm = hs.loadSpoon("PaperWM")
if not paperwm then
  print("PaperWM.spoon not installed in ~/.hammerspoon/Spoons/. Run desktop/hammerspoon/install.sh to install.")
  return
end

-- Layout & Gaps
paperwm.window_gap = { top = 8, bottom = 8, left = 8, right = 8 }
paperwm.window_ratios = { 0.333, 0.5, 0.666 }
paperwm.default_width = 0.5
paperwm.infinite_loop_window = false
paperwm.center_mouse = false

-- App-specific default widths (ratios)
paperwm.app_widths = {
  ["Google Chrome"] = 0.5,
  ["com.mitchellh.ghostty"] = 0.5,
  ["md.obsidian"] = 0.5,
}

-- Window Filter: exempt floating utilities, dialogs, screen grab and remote desktop apps
paperwm.window_filter:rejectApp("Shottr")
paperwm.window_filter:rejectApp("Maccy")
paperwm.window_filter:rejectApp("UURemote")
paperwm.window_filter:rejectApp("CleanMyMac X")
paperwm.window_filter:rejectApp("1Password")
paperwm.window_filter:rejectApp("System Settings")
paperwm.window_filter:rejectApp("System Preferences")
paperwm.window_filter:rejectApp("Archive Utility")
paperwm.window_filter:rejectApp("Activity Monitor")
paperwm.window_filter:rejectApp("WeChat")
paperwm.window_filter:rejectApp("com.tencent.xinWeChat")
paperwm.window_filter:rejectApp("Hammerspoon")
paperwm.window_filter:rejectApp("QuickTime Player")
paperwm.window_filter:rejectApp("Calculator")

-- Keybindings (Alt+Cmd for navigation/layout, Alt+Cmd+Shift for movement/float)
paperwm:bindHotkeys({
  -- Focus navigation (Vim h/j/k/l & Arrows)
  focus_left  = { { "alt", "cmd" }, "h" },
  focus_right = { { "alt", "cmd" }, "l" },
  focus_up    = { { "alt", "cmd" }, "k" },
  focus_down  = { { "alt", "cmd" }, "j" },

  -- Window swapping / movement
  swap_left   = { { "alt", "cmd", "shift" }, "h" },
  swap_right  = { { "alt", "cmd", "shift" }, "l" },
  swap_up     = { { "alt", "cmd", "shift" }, "k" },
  swap_down   = { { "alt", "cmd", "shift" }, "j" },

  -- Width & Column management
  cycle_width       = { { "alt", "cmd" }, "r" },
  full_width        = { { "alt", "cmd" }, "f" },
  center_window     = { { "alt", "cmd" }, "c" },
  slurp_in          = { { "alt", "cmd" }, "i" },
  barf_out          = { { "alt", "cmd" }, "o" },
  split_screen      = { { "alt", "cmd" }, "s" },

  -- Floating layers
  toggle_floating   = { { "alt", "cmd", "shift" }, "space" },
  focus_floating    = { { "alt", "cmd", "shift" }, "f" },

  -- Retile / Refresh
  refresh_windows   = { { "alt", "cmd", "shift" }, "r" },
})

paperwm:start()
print("PaperWM.spoon initialized and started.")
