# Activity icon labels

Activity names belong in the UI label beside or below the icon. Do not bake small names, protocol captions or activity captions into the artwork; the palette, picker and canvas already provide labels.

Keep SVG titles for accessibility. The End stop sign retains its large central “End” text as part of the symbol; it must not have an additional small caption embedded beneath the sign.

The UI loads SVG artwork from `frontend/src/assets/activity-icons` through the shared `activityIconUrl` loader. These bundled SVGs receive fresh build-managed URLs or inline data when they change, preventing stale embedded captions in both the canvas and activity picker. Update the bundled asset when changing an icon; public copies are retained for compatibility with older builds. Legacy PNG artwork has been visually checked for activity captions.
