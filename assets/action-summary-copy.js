(function () {
  const host = window.parent;
  const doc = host.document;
  const decode = value => new TextDecoder().decode(Uint8Array.from(atob(value), ch => ch.charCodeAt(0)));
  const fallbackCopy = (text, button) => {
    const field = doc.createElement('textarea');
    field.value = text;
    field.style.cssText = 'position:fixed;left:0;top:0;opacity:0;width:1px;height:1px;';
    (button.closest('[role="dialog"]') || doc.body).appendChild(field);
    field.focus();
    field.select();
    let copied = false;
    try { copied = doc.execCommand('copy'); } finally { field.remove(); button.focus(); }
    return copied;
  };
  const bind = () => {
    doc.querySelectorAll('.action-summary-copy:not([data-copy-bound])').forEach(button => {
      button.dataset.copyBound = 'true';
      button.addEventListener('click', async () => {
        if (button.disabled) return;
        host.clearTimeout(button.copyFeedbackTimer);
        const feedback = button.parentElement.querySelector('.action-summary-feedback');
        const label = button.querySelector('span');
        const text = decode(button.dataset.actionSummary);
        try {
          try {
            if (!host.navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
            await host.navigator.clipboard.writeText(text);
          } catch (error) {
            if (!fallbackCopy(text, button)) throw error;
          }
          label.textContent = 'Copied ✓';
          button.classList.add('copied');
          feedback.textContent = 'Summary copied.';
          button.copyFeedbackTimer = host.setTimeout(() => {
            label.textContent = 'Copy Summary';
            button.classList.remove('copied');
            feedback.textContent = '';
          }, 2200);
        } catch (error) {
          label.textContent = 'Copy Summary';
          button.classList.remove('copied');
          feedback.textContent = 'Copy unavailable. Select the summary below and copy it manually.';
          let field = button.parentElement.querySelector('textarea');
          if (!field) {
            field = doc.createElement('textarea');
            field.className = 'action-summary-manual';
            field.readOnly = true;
            field.setAttribute('aria-label', 'Action summary');
            button.parentElement.appendChild(field);
          }
          field.value = text;
          field.focus();
          field.select();
        }
      });
    });
  };
  const observer = new host.MutationObserver(bind);
  observer.observe(doc.body, {childList: true, subtree: true});
  bind();
  window.addEventListener('unload', () => observer.disconnect(), {once: true});
})();
