const address = document.getElementById('address'), status = document.getElementById('status'), button = document.getElementById('connect');
window.minaConnection.settings().then(value => {address.value=value; address.focus();}).catch(() => {status.textContent='Unable to read saved address. You can enter it below.';});
document.getElementById('connection').addEventListener('submit', async event => {
  event.preventDefault(); button.disabled=true; status.textContent='Connecting…';
  try { const result=await window.minaConnection.connect(address.value); status.textContent=result.error || ''; }
  catch { status.textContent='Unable to connect. Check the server address and try again.'; }
  finally { button.disabled=false; }
});
