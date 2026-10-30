import hashlib
import io
import json

from odoo import _
from odoo.exceptions import AccessError
from odoo.tools.pdf import PdfReader

from odoo.addons.approval_center.models.common import capability

internal, trusted = capability('_ai_agent_token')


def manager(records):
    if not records.env.user.has_group('ai_agent.group_manager'):
        raise AccessError(_('Only AI Agent managers can configure assistants.'))
    records.check_access('write' if records else 'create')
    if records and any(r.company_id not in records.env.companies for r in records):
        raise AccessError(_('Select the authorized company first.'))


def loading_demo(records):
    """True while Odoo loads this module's demo data files (demo/*.xml), the only place demo-only values come from."""
    context = records.env.context
    return bool(context.get('install_mode') and context.get('install_module') == 'ai_agent'
                and '/demo/' in '/' + (context.get('install_filename') or '').replace('\\', '/'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


TEXT_FILE_SUFFIXES = ('.txt', '.md', '.csv')
FILE_MAX_BYTES = 5 * 1024 * 1024
TEXT_MAX_CHARS = 200000


def extract_text(raw, filename, max_pages=100):
    """Plain text of a readable PDF or UTF-8 text file; ValueError otherwise.

    Shared by knowledge sources and chat attachments, so both accept the same
    formats and limits.
    """
    raw = raw.content if hasattr(raw, 'content') else raw  # Odoo 20 Binary fields return BinaryValue
    if not raw or len(raw) > FILE_MAX_BYTES:
        raise ValueError('size')
    if raw.startswith(b'%PDF-'):
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or len(reader.pages) > max_pages:
            raise ValueError('pdf limits')
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    elif (filename or '').lower().endswith(TEXT_FILE_SUFFIXES):
        text = raw.decode('utf-8')
    else:
        raise ValueError('format')
    if not text.strip() or len(text) > TEXT_MAX_CHARS:
        raise ValueError('text limits')
    return text
