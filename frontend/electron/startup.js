const statusLabel = document.getElementById('startup-label');
const progress = document.getElementById('startup-progress');
let lastElapsed = -1;
const showStatus = (status) => {
  if (!status || status.elapsedMs < lastElapsed) return;
  lastElapsed = status.elapsedMs;
  statusLabel.textContent = status.label;
  progress.max = status.total;
  progress.value = status.step;
};
window.minaDesktop?.onStartupStatus?.(showStatus);
window.minaDesktop?.getStartupStatus?.().then(showStatus).catch(() => {});
