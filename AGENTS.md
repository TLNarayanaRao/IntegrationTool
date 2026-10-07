# UI layout requirements

- Full-screen popup dialogs must fit inside the current viewport, including short windows and larger font settings. Keep close and action controls reachable and scroll long content.
- Use `frontend/src/ModalLayer.tsx` for full-screen dialogs so configuration panels, ribbons, and splitters cannot clip or overlap them.
- Report changed files with clickable links and a brief description in completion reports.
