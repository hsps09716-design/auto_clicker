# Auto Clicker

A focused Windows desktop auto clicker with click recording, precise timing, reusable profiles, and JSON import/export.

## Features

- Add clicks with custom screen coordinates and per-click delays.
- Capture the current cursor position.
- Record global left-click positions, order, and timing.
- Reorder, edit, or delete individual steps.
- Save, load, and delete multiple named profiles.
- Import and export portable JSON profiles.
- Configure a start countdown and repeat count.
- Restore the last session automatically.

## Hotkeys

| Action | Hotkey |
| --- | --- |
| Start or stop recording | `Ctrl + Alt + R` |
| Emergency stop playback | `Ctrl + Alt + S` |

The same actions are always available through the on-screen buttons.

## Run from source

Requires Windows and Python 3.11 or newer with Tk support.

```powershell
python app.py
```

The application uses only Python's standard library.

## Profile storage

Named profiles and the last session are stored under `%LOCALAPPDATA%\AutoClicker`. Profiles can also be exported as JSON files for backup or sharing.

## Safety

Playback moves the system cursor and sends real left-clicks. A three-second start delay is enabled by default. Confirm the sequence before starting and use the STOP button or `Ctrl + Alt + S` when needed.

Some administrator-level applications can only be automated when Auto Clicker is started with matching permissions.

