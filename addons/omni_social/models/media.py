"""Ordered, team-scoped media; the parent approval freezes bytes and order."""

import hashlib
import io
import json
import subprocess
import tempfile
from PIL import Image
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from .social import guarded


def _probe(raw):
    with tempfile.NamedTemporaryFile(suffix='.mp4') as handle:
        handle.write(raw)
        handle.flush()
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-protocol_whitelist', 'file', '-f', 'mov',
             '-show_streams', '-show_format', '-of', 'json', handle.name],
            capture_output=True, timeout=15, check=True,
        )
    return json.loads(probe.stdout)


class Media(models.Model):
    _name = 'omni.social.media'
    _description = 'Social Media'
    _order = 'sequence,id'
    publication_id = fields.Many2one('omni.social.publication', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='publication_id.company_id', store=True)
    purpose_id = fields.Many2one(related='publication_id.purpose_id', store=True)
    sequence = fields.Integer(default=10, string='Order')
    name = fields.Char(required=True, string='Filename')
    kind = fields.Selection([('image', 'Photo'), ('video', 'Video')], required=True, default='image')
    file = fields.Binary(required=True, attachment=False, string='File')
    alt_text = fields.Char(string='Description')

    preview = fields.Binary(compute='_compute_preview')
    # Read from the file when it is saved; shown next to the file and in the preview.
    file_size = fields.Integer(compute='_compute_metadata', store=True, string='Size (bytes)')
    width = fields.Integer(compute='_compute_metadata', store=True)
    height = fields.Integer(compute='_compute_metadata', store=True)
    duration = fields.Float(compute='_compute_metadata', store=True, string='Length (s)')

    @api.depends('file', 'kind')
    def _compute_metadata(self):
        for row in self:
            raw = row.file.content if row.file else b''
            row.file_size, row.width, row.height, row.duration = len(raw), 0, 0, 0.0
            if not raw:
                continue
            try:
                if row.kind == 'image':
                    with Image.open(io.BytesIO(raw)) as img:
                        row.width, row.height = img.size
                else:
                    info = _probe(raw)
                    video = [s for s in info.get('streams', []) if s.get('codec_type') == 'video'][:1]
                    if video:
                        row.width, row.height = int(video[0].get('width') or 0), int(video[0].get('height') or 0)
                    row.duration = float((info.get('format') or {}).get('duration') or 0)
            except Exception:  # noqa: BLE001 - unreadable files are reported when the post is submitted
                continue

    @api.depends('file', 'kind')
    def _compute_preview(self):
        for row in self:
            row.preview = row.file if row.kind == 'image' else False

    @api.constrains('file')
    def _check_size(self):
        for row in self:
            if row.file and len(row.file.content) > 64 * 1024 * 1024:
                raise UserError(_('Media must be under 64 MB.'))

    def _editable(self):
        for row in self:
            parent = row.publication_id
            parent.check_access('write')
            parent._lock()
            if parent.state != 'draft' or parent.requester_id != self.env.user:
                raise AccessError(_('Only the owner can edit draft media.'))

    @api.model_create_multi
    def create(self, values):
        guarded(self, {'company_id', 'purpose_id'}, values)
        for val in values:
            parent = (
                self.env['omni.social.publication']
                .browse(val.get('publication_id') or self.env.context.get('default_publication_id'))
                .exists()
            )
            if not parent:
                raise AccessError(_('Choose a draft.'))
            parent.check_access('write')
            parent._lock()
            if parent.state != 'draft' or parent.requester_id != self.env.user:
                raise AccessError(_('Only the owner can add draft media.'))
        return super().create(values)

    def write(self, values):
        guarded(self, {'company_id', 'purpose_id', 'publication_id'}, [values])
        self._editable()
        return super().write(values)

    def unlink(self):
        self._editable()
        return super().unlink()

    def _manifest(self, token, index):
        self.ensure_one()
        raw = self.file.content
        if not raw:
            raise UserError(_('Upload each media file.'))
        if self.kind == 'image':
            if len(raw) > 8 * 1024 * 1024:
                raise UserError(_('Photos must be JPEG and under 8 MB.'))
            try:
                with Image.open(io.BytesIO(raw)) as img:
                    if img.format != 'JPEG' or img.width * img.height > 24000000:
                        raise ValueError()
                    img.verify()
            except Exception:
                raise UserError(_('Upload a valid JPEG photo.')) from None
            mime = 'image/jpeg'
            metadata = {}
        else:
            if len(raw) > 64 * 1024 * 1024:
                raise UserError(_('Videos must be MP4 and under 64 MB.'))
            try:
                with tempfile.NamedTemporaryFile(suffix='.mp4') as handle:
                    handle.write(raw)
                    handle.flush()
                    probe = subprocess.run(
                        [
                            'ffprobe',
                            '-v',
                            'error',
                            '-protocol_whitelist',
                            'file',
                            '-f',
                            'mov',
                            '-show_streams',
                            '-show_format',
                            '-of',
                            'json',
                            handle.name,
                        ],
                        capture_output=True,
                        timeout=15,
                        check=True,
                    )
                    info = json.loads(probe.stdout)
                video = [s for s in info['streams'] if s['codec_type'] == 'video']
                audio = [s for s in info['streams'] if s['codec_type'] == 'audio']
                duration = float(info['format']['duration'])
                if (
                    len(video) != 1
                    or video[0]['codec_name'] not in ('h264', 'hevc')
                    or not 3 <= duration <= 900
                    or video[0]['width'] > 1920
                    or 'mp4' not in info['format']['format_name']
                    or any(a['codec_name'] != 'aac' for a in audio)
                ):
                    raise ValueError()
                rate = video[0]['avg_frame_rate'].split('/')
                fps = float(rate[0]) / float(rate[1])
                if not 23 <= fps <= 60:
                    raise ValueError()
                if self.publication_id.format in ('story', 'carousel') and duration > 60:
                    raise ValueError()
                metadata = {'duration': duration, 'width': video[0]['width'], 'height': video[0]['height']}
            except Exception:
                raise UserError(
                    _('Use an MP4 video: H.264/HEVC, 23–60 fps, 3–900 seconds (stories: 60 max).')
                ) from None
            mime = 'video/mp4'
        parent = self.publication_id
        url = ''
        caps = parent.connection_id._caps()
        if caps and caps.needs_public_url:
            if not parent.connection_id.public_url:
                raise UserError(_('Set the account’s public HTTPS address.'))
            url = parent.connection_id.public_url.rstrip('/') + '/omni/social/media/' + token + '/' + str(index)
        return {
            'id': self.id,
            'kind': self.kind,
            'digest': hashlib.sha256(raw).hexdigest(),
            'url': url,
            'mime': mime,
            'name': self.name,
            'alt_text': self.alt_text or '',
            **metadata,
        }
