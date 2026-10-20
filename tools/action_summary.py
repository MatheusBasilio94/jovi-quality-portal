"""WhatsApp-ready summaries of saved action cards. No messages are sent."""
import base64
from datetime import date

from tools.br_datetime import br_date
from tools.defect_actions import action_code, local_today


def build_action_summary(record, today=None):
    today = today or local_today()
    text = lambda key: str(record.get(key) or '').strip()
    notification = text('status') == 'Notification'
    lines = ['📋 *QUALITY NOTIFICATION*' if notification else '📋 *QUALITY ACTION*', '']
    lines.append(f"*Code:* {action_code(record) or 'Pending'}")
    for key, label in [('title','Action'), ('area','Area'), ('model','Model'), ('owner','Owner'),
                       ('priority','Priority'), ('status','Status')]:
        lines.append(f"*{label}:* {text(key) or 'Pending'}")
    lines.append(f"*Due date:* {br_date(text('due_date')) if text('due_date') else 'Pending'}")
    if text('due_date'):
        due = date.fromisoformat(text('due_date'))
        late = (today-due).days
        if late > 0 and text('status') not in {'Closed', 'Notification'}:
            lines.append(f"🔴 *Overdue:* {late} {'day' if late==1 else 'days'}")
    for key, heading in [('defect','🔎 *Related defect*'), ('root_cause','*Problem / root cause*'),
                         ('containment','🛡️ *Containment*'), ('countermeasure','🔧 *Countermeasure*')]:
        lines.extend(['', heading, text(key) or 'Pending'])
    lines.extend(['', '✅ *Effectiveness verification*'])
    if notification:
        lines.append('Not applicable — occurrence recorded for monitoring.')
    elif record.get('verified'):
        lines.append('Verified' + (f" — closed on {br_date(record['closed_at'])}." if record.get('closed_at') else '.'))
    else:
        lines.append('Pending — record the validation results before closing the action.')
    lines.append(f"*Evidence:* {text('evidence') or 'Pending'}")
    return '\n'.join(lines)


def copy_summary_html(record, today=None):
    enabled = bool(record.get('id'))
    encoded = base64.b64encode(build_action_summary(record, today).encode('utf-8')).decode('ascii') if enabled else ''
    hint = 'Copy action summary to share on WhatsApp. Copies saved information.' if enabled else 'Save the action before copying its summary.'
    disabled = '' if enabled else ' disabled'
    return (f'<div class="action-summary-toolbar"><button type="button" class="action-summary-copy" '
            f'data-action-summary="{encoded}" title="{hint}" aria-label="Copy Summary"{disabled}>'
            '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
            '<rect x="8" y="8" width="12" height="13" rx="2"></rect><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"></path></svg>'
            '<span>Copy Summary</span></button><span class="action-summary-feedback" role="status" aria-live="polite"></span></div>')
