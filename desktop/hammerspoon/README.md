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

## PaperWM Scrollable Tiling

PaperWM (`PaperWM.spoon`) provides an infinite horizontal ribbon tiling layout
for macOS without requiring SIP (System Integrity Protection) modifications.

### Keybindings

| Action | Shortcut |
|---|---|
| Focus Left / Right | `Alt + Cmd + H` / `L` or `Alt + Cmd + Left` / `Right` |
| Focus Up / Down | `Alt + Cmd + K` / `J` or `Alt + Cmd + Up` / `Down` |
| Swap Window Left / Right | `Alt + Cmd + Shift + H` / `L` |
| Swap Window Up / Down | `Alt + Cmd + Shift + K` / `J` |
| Cycle Window Width (1/3, 1/2, 2/3) | `Alt + Cmd + R` |
| Toggle Full Width | `Alt + Cmd + F` |
| Center Focused Window | `Alt + Cmd + C` |
| Slurp into Column | `Alt + Cmd + I` |
| Barf out of Column | `Alt + Cmd + O` |
| Split Screen with Left Window | `Alt + Cmd + S` |
| Toggle Floating Window | `Alt + Cmd + Shift + Space` |
| Focus Floating Windows | `Alt + Cmd + Shift + F` |
| Force Retile Windows | `Alt + Cmd + Shift + R` |

### System Settings Requirement

Open **System Settings → Desktop & Dock → Mission Control**:
1. **Disable**: *Automatically rearrange Spaces based on most recent use*
2. **Enable**: *Displays have separate Spaces*

### Window Filter Exclusions

Floating utilities (`Shottr`, `Maccy`, `1Password`, `CleanMyMac X`, `WeChat`, `System Settings`, `UURemote`) are automatically excluded from the tiling grid in `paperwm.lua`.
