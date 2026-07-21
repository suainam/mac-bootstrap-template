# Hammerspoon

This directory owns macOS-global hotkeys, window placement, clipboard helpers,
and terminal launcher integration. Input methods remain user-controlled.

## Install and reload

Run `install.sh` to link this tracked configuration into `~/.hammerspoon`.
After changing the configuration, restart the existing application process:

```bash
killall Hammerspoon && open -a Hammerspoon
```

Do not use `hammerspoon -c "hs.reload()"`. That command starts another process
rather than sending IPC to the running app and can produce duplicate hotkey
registration failures such as `RegisterEventHotKey failed: -9878`.
