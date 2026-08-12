# Hammerspoon

This directory owns macOS-global hotkeys, window placement, clipboard helpers,
and terminal launcher integration. Input methods remain user-controlled.

## Install and reload

Run `install.sh` to link this tracked configuration into `~/.hammerspoon`.
After changing the configuration, restart the existing application process:

```bash
killall Hammerspoon && open -a Hammerspoon
```

## Clipboard history

Clipboard history is owned by Maccy, installed from the Brewfile. Maccy does
not run through Hammerspoon. Its default popup shortcut is `Shift+Command+C`;
configure `Hyper+V` in Maccy's Preferences if you want to preserve the old
Hammerspoon shortcut.

Enable Maccy's automatic paste option and add Maccy to
System Settings → Privacy & Security → Accessibility if selecting a history
item should paste into the focused application. The `Ctrl+Shift+V` Hammerspoon
hotkey remains available for saving the current clipboard image under
`~/Pictures/ClipboardShots`.

Do not use `hammerspoon -c "hs.reload()"`. That command starts another process
rather than sending IPC to the running app and can produce duplicate hotkey
registration failures such as `RegisterEventHotKey failed: -9878`.
