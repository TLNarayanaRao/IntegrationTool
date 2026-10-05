/** Advance within the active editor, skipping collapsed or unavailable inputs. */
export function focusNextMapping(current: HTMLInputElement | HTMLTextAreaElement) {
  const scope = current.closest('.activity-tab') || current.closest('[role="dialog"]') || current.form || current.parentElement;
  if (!scope) { current.blur(); return; }
  const fields = Array.from(scope.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('[data-mapping-input]'))
    .filter(field => !field.disabled && !field.readOnly && field.getClientRects().length > 0);
  const next = fields[fields.indexOf(current) + 1];
  if (next && next !== current) { next.focus(); next.select(); }
  else current.blur();
}
