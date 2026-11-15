"""Where a design goes (plan M6, approved board 13.4 B): a social post, an email, a proof; and the other way round,
"From Designs" on a social post and under a proof's Creative. Nothing is sent or published from here: the post, the
mailing and the proof follow their usual reviews.
"""

import base64

from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import BinaryBytes

from . import render
from .design import FORMATS, LIMITS
from odoo.addons.omni_social.providers.registry import capabilities


def _form(record, name=None):
    return {'type': 'ir.actions.act_window', 'res_model': record._name, 'res_id': record.id, 'view_mode': 'form',
            'views': [(False, 'form')], 'target': 'current', **({'name': name} if name else {})}


class Design(models.Model):
    _inherit = 'mi.design'

    def _pictures(self):
        """[(file name, PNG bytes)] of the design, one per slide, in order."""
        self.ensure_one()
        name = self._file_name()
        images = self._images()
        if len(images) == 1:
            return [(name + '.png', render.png(images[0]))]
        return [('%s-%02d.png' % (name, index), render.png(image)) for index, image in enumerate(images, start=1)]

    def _media_commands(self, start=0):
        return [Command.create({'name': name, 'kind': 'image', 'file': BinaryBytes(content),
                                'sequence': start + index * 10})
                for index, (name, content) in enumerate(self._pictures(), start=1)]

    def action_use_social(self):
        """A social post: a new draft with the picture (or every slide, in order) as its media."""
        self.ensure_one()
        if 'social' not in (self.use_targets or '').split(','):
            raise UserError(_('This design cannot be used in a social post.'))
        connections = self.brand_id._accounts('omni.social.connection') \
            or self.env['omni.social.connection'].search([('company_id', '=', self.company_id.id)])
        if not connections:
            raise UserError(_('Connect a social account first (Social › Accounts), then use the design in a post.'))
        # The brand's first account that can post this kind (a carousel, a story); the person can change it.
        wanted = 'carousel' if len(self.slide_ids) > 1 else 'story' if self.format == 'story' else 'standard'

        def formats(connection):
            caps = capabilities(connection.provider)
            return caps.formats if caps else ()

        connection = connections.filtered(lambda c: wanted in formats(c))[:1] or connections[:1]
        slide = self.slide_ids[:1]
        post = self.env['omni.social.publication'].create({
            'name': self.name, 'connection_id': connection.id,
            'body': '\n\n'.join(filter(None, [slide.headline, slide.text])),
            'reason': _('Made from the design "%s".', self.name),
            'format': wanted if wanted in formats(connection) else 'standard',
            'media_ids': self._media_commands(),
        })
        return _form(post)

    def _use_wizard(self, target, name):
        self.ensure_one()
        if target not in (self.use_targets or '').split(','):
            raise UserError(_('This design cannot be used there.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.design.use', 'view_mode': 'form', 'target': 'new',
                'name': name, 'context': {'default_design_id': self.id, 'default_target': target,
                                          'default_plan_id': self.plan_id.id}}

    def action_use_email(self):
        return self._use_wizard('email', _('Use in an email'))

    def action_use_proof(self):
        return self._use_wizard('proof', _('Use in a proof for review'))


class DesignUse(models.TransientModel):
    _name = 'mi.design.use'
    _description = 'Use a design'

    target = fields.Selection([('email', 'An email'), ('proof', 'A proof for review'),
                               ('post', 'This social post'), ('proof_image', 'This proof')], required=True)
    design_id = fields.Many2one('mi.design', string='Design', required=True)
    plan_id = fields.Many2one('mi.plan', string='Campaign')
    mailing_id = fields.Many2one('mailing.mailing', string='Draft mailing',
                                 domain="[('state', '=', 'draft'), ('mailing_type', '=', 'mail')]",
                                 help='Leave empty for a new mailing.')
    proof_id = fields.Many2one('mi.proof', string='Proof',
                               domain="[('plan_id', '=', plan_id), ('state', 'in', ('draft', 'changes', 'approved'))]",
                               help='Leave empty for a new proof. An existing proof gets a new version.')
    publication_id = fields.Many2one('omni.social.publication')
    target_proof_id = fields.Many2one('mi.proof')

    def action_apply(self):
        self.ensure_one()
        design = self.design_id
        design.check_access('read')
        return getattr(self, '_apply_' + self.target)(design)

    def _apply_email(self, design):
        """The picture at the top of a draft mailing's body. The mailing turns it into a file it serves itself."""
        if design.format != 'email_header':
            raise UserError(_('Only an email header goes into an email.'))
        _name, content = design._pictures()[0]
        picture = Markup('<p style="margin:0"><img src="data:image/png;base64,%s" alt="%s" '
                         'style="max-width:100%%;height:auto"/></p>') % (base64.b64encode(content).decode(),
                                                                         design.name)
        mailing = self.mailing_id
        if mailing:
            if mailing.state != 'draft':
                raise UserError(_('Choose a mailing that is still a draft.'))
            mailing.write({'body_arch': picture + (mailing.body_arch or ''),
                           'body_html': picture + (mailing.body_html or '')})
        else:
            mailing = self.env['mailing.mailing'].create({'subject': design.name, 'mailing_type': 'mail',
                                                          'body_arch': picture, 'body_html': picture})
        return _form(mailing)

    def _apply_proof(self, design):
        """The picture as the Creative of a proof: a new proof, or a new version of the one chosen."""
        plan = self.plan_id or design.plan_id
        _name, content = design._pictures()[0]
        proof = self.proof_id
        if proof:
            if proof.state in ('approved', 'changes'):
                proof = self.env['mi.proof'].browse(proof.action_new_version()['res_id'])
            proof.image = BinaryBytes(content)
        else:
            if not plan:
                raise UserError(_('Choose the campaign the proof is for.'))
            proof = self.env['mi.proof'].create({'name': design.name, 'plan_id': plan.id,
                                                 'subject': design.slide_ids[:1].headline,
                                                 'image': BinaryBytes(content)})
        return _form(proof)

    def _apply_post(self, design):
        """From Designs on a social post: the design's pictures are added to the post's media."""
        post = self.publication_id
        if not post or post.state != 'draft':
            raise UserError(_('Pictures are added while the post is a draft.'))
        if design.format == 'email_header':
            raise UserError(_('An email header is not made for a social post.'))
        start = max(post.media_ids.mapped('sequence') or [0])
        post.write({'media_ids': design._media_commands(start)})
        return {'type': 'ir.actions.act_window_close'}

    def _apply_proof_image(self, design):
        proof = self.target_proof_id
        if not proof or proof.state in ('review', 'approved', 'old'):
            raise UserError(_('The creative changes while the proof is a draft; make a new version first.'))
        proof.image = BinaryBytes(design._pictures()[0][1])
        return {'type': 'ir.actions.act_window_close'}


class DesignCopy(models.TransientModel):
    _name = 'mi.design.copy'
    _description = 'Copy a design to another format'

    design_id = fields.Many2one('mi.design', required=True)
    format = fields.Selection(FORMATS, required=True, default='portrait')
    paper = fields.Selection([('a4', 'A4'), ('a3', 'A3')], default='a4', required=True, string='Poster size')

    def action_copy(self):
        """The same template and texts in another format. A carousel keeps its slides only as a carousel; any other
        format takes the slide being edited."""
        self.ensure_one()
        design = self.design_id
        labels = dict(self._fields['format']._description_selection(self.env))
        values = {'name': '%s (%s)' % (design.name, labels[self.format]), 'format': self.format, 'paper': self.paper}
        if self.format != 'carousel' or design.format != 'carousel':
            source = design._active()
            slides = [Command.create(source.copy_data()[0] | {'design_id': False, 'sequence': 10})]
            if self.format == 'carousel':
                slides += [Command.create({'sequence': 20, 'look': source.look}),
                           Command.create({'sequence': 30, 'look': source.look})]
            values['slide_ids'] = slides
        return _form(design.copy(values))


class DesignNew(models.TransientModel):
    """New design (board 13.2): the format first, then a template."""
    _name = 'mi.design.new'
    _description = 'New design'

    format = fields.Selection(FORMATS, required=True, default='square')
    paper = fields.Selection([('a4', 'A4'), ('a3', 'A3')], default='a4', required=True, string='Poster size')
    template_id = fields.Many2one('mi.design.template', string='Template', required=True,
                                  default=lambda self: self.env['mi.design.template'].search([], limit=1))
    plan_id = fields.Many2one('mi.plan', string='Campaign')
    brand_id = fields.Many2one('mi.brand', string='Brand', required=True,
                               default=lambda self: self.env['mi.design']._default_brand())
    kit_empty = fields.Boolean(related='brand_id.kit_empty')

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        if self.plan_id:
            self.brand_id = self.plan_id.brand_id

    def action_create(self):
        self.ensure_one()
        labels = dict(self._fields['format']._description_selection(self.env))
        design = self.env['mi.design'].create({
            'name': '%s · %s' % (self.template_id.name, labels[self.format]), 'format': self.format, 'paper': self.paper, 'template_id': self.template_id.id,
            'plan_id': self.plan_id.id, 'brand_id': self.brand_id.id})
        return _form(design)

    def action_open_brand_kit(self):
        self.ensure_one()
        return _form(self.brand_id)


class Publication(models.Model):
    _inherit = 'omni.social.publication'

    def action_mi_from_designs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.design.use', 'view_mode': 'form', 'target': 'new',
                'name': _('From Designs'),
                'context': {'default_target': 'post', 'default_publication_id': self.id}}


class Media(models.Model):
    _inherit = 'omni.social.media'

    def action_mi_use_in_design(self):
        """From the library: this photo goes on the slide being edited."""
        self.ensure_one()
        slide = self.env['mi.design.slide'].browse(self.env.context.get('mi_slide_id')).exists()
        if not slide or self.kind != 'image' or not self.file:
            raise UserError(_('Choose a photo for the slide.'))
        slide._set_picture(self.file.content)
        return {'type': 'ir.actions.act_window_close'}


class Proof(models.Model):
    _inherit = 'mi.proof'

    def action_mi_from_designs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.design.use', 'view_mode': 'form', 'target': 'new',
                'name': _('From Designs'),
                'context': {'default_target': 'proof_image', 'default_target_proof_id': self.id,
                            'default_plan_id': self.plan_id.id}}


class Plan(models.Model):
    _inherit = 'mi.plan'

    design_ids = fields.One2many('mi.design', 'plan_id', string='Designs')
    design_count = fields.Integer(compute='_compute_design_count')

    @api.depends('design_ids')
    def _compute_design_count(self):
        for plan in self:
            plan.design_count = len(plan.design_ids)

    def action_open_designs(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('marketing_intel_design.action_designs')
        action['domain'] = [('plan_id', '=', self.id)]
        action['context'] = {'default_plan_id': self.id}
        return action


class Writing(models.AbstractModel):
    _inherit = 'mi.writing'

    @api.model
    def _prompt(self, kind, action, text, option, values):
        if not (kind or '').startswith('design_'):
            return super()._prompt(kind, action, text, option, values)
        what = {'design_headline': 'the headline', 'design_text': 'the short text',
                'design_button': 'the button text'}[kind]
        prompt = super()._prompt('campaign', action, text, option, values)
        prompt = prompt.replace('a text of a marketing campaign plan',
                                '%s of a designed social post, poster or email header' % what)
        limit = LIMITS[kind.removeprefix('design_')]
        return prompt.replace('The text to work on is between the markers.',
                              'Never go over %s characters.\nThe text to work on is between the markers.' % limit)
