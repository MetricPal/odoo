"""Customisable control panel: which blocks show, in which order and width, saved per person or per role.

A layout is an ordered list of blocks: the panel's own (numbers, timeline, to-dos, alerts, campaigns,
workflows, ... — other marketing modules add theirs) and boxes from Report Studio reports. Managers save
views for a role (marketer, advisor, manager); anyone saves their own view, starting from their role's.
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

ROLES = [('marketer', 'Marketer'), ('advisor', 'Advisor (client brands)'), ('manager', 'Marketing manager')]
WIDTHS = ('full', 'half')
DEFAULT_BLOCKS = {
    'marketer': ['kpis', 'timeline', 'todos', 'alerts', 'campaigns', 'flows'],
    'advisor': ['kpis', 'todos', 'alerts', 'timeline', 'campaigns', 'flows'],
    'manager': ['kpis', 'alerts', 'todos', 'timeline', 'campaigns', 'flows'],
}
FULL = ('kpis', 'campaigns', 'flows')


class PanelLayout(models.Model):
    _name = 'mi.panel.layout'
    _description = 'Marketing control panel view'
    _order = 'user_id, role, id'

    name = fields.Char(required=True)
    user_id = fields.Many2one('res.users', string='Person', ondelete='cascade', index=True,
                              help='Empty: a role view, shared by everyone with that role.')
    role = fields.Selection(ROLES, help='The role this view is for (role views) or started from (personal views).')
    blocks = fields.Json(help='Ordered blocks: [{"key": "timeline", "width": "half"}, '
                              '{"key": "report", "report_block_id": 7, "width": "half"}]')

    _role_unique = models.UniqueIndex('(role) WHERE user_id IS NULL', 'One shared view per role.')

    # ------------------------------------------------------------------ catalogue
    @api.model
    def _catalogue(self):
        """Built-in blocks: key -> label. Other modules extend it (and fill the data in mi.panel)."""
        return {'kpis': _('Numbers'), 'timeline': _('Timeline'), 'todos': _('Your action needed'),
                'alerts': _('Alerts'), 'campaigns': _('Campaigns in progress'), 'flows': _('Workflows')}

    @api.model
    def _default_blocks(self, role):
        catalogue = self._catalogue()
        return [{'key': key, 'width': 'full' if key in FULL else 'half'}
                for key in DEFAULT_BLOCKS.get(role, DEFAULT_BLOCKS['marketer']) if key in catalogue]

    @api.model
    def _user_role(self, user=None):
        user = user or self.env.user
        if user.has_group('marketing_intel.group_mi_manager'):
            return 'manager'
        brands = self.env['mi.brand'].with_user(user).search([])
        if brands.filtered(lambda b: b.owner_type == 'client'):
            return 'advisor'
        return 'marketer'

    def _clean(self, blocks):
        """Keep known blocks only, each once (report boxes once per box), with a valid width."""
        catalogue, seen, clean = self._catalogue(), set(), []
        Box = self.env['report.studio.block']
        for block in blocks or []:
            if not isinstance(block, dict):
                continue
            key = block.get('key')
            width = block.get('width') if block.get('width') in WIDTHS else 'half'
            if key == 'report':
                box = Box.browse(int(block.get('report_block_id') or 0)).exists()
                if not box or ('report', box.id) in seen:
                    continue
                seen.add(('report', box.id))
                clean.append({'key': 'report', 'report_block_id': box.id, 'width': width})
            elif key in catalogue and key not in seen:
                seen.add(key)
                clean.append({'key': key, 'width': width})
        return clean

    # ------------------------------------------------------------------ which layout applies
    @api.model
    def _role_layout(self, role):
        return self.sudo().search([('user_id', '=', False), ('role', '=', role)], limit=1)

    @api.model
    def _current(self):
        """(layout record or empty, blocks, role) for the current user."""
        user = self.env.user
        view = user.mi_panel_view
        if view in dict(ROLES):
            role = view
        else:
            mine = self.sudo().search([('user_id', '=', user.id)], limit=1)
            if mine:
                return mine, self._clean(mine.blocks), mine.role or self._user_role()
            role = self._user_role()
        layout = self._role_layout(role)
        return layout, (self._clean(layout.blocks) if layout else self._default_blocks(role)), role

    @api.model
    def get_layout_info(self):
        layout, blocks, role = self._current()
        user = self.env.user
        reports = self.env['report.studio.report'].search([], limit=100)
        boxes = self.env['report.studio.block'].search([('report_id', 'in', reports.ids), ('type', '!=', 'heading')],
                                                       limit=200, order='report_id, sequence, id')
        return {
            'blocks': blocks,
            'view': user.mi_panel_view or ('mine' if layout.user_id else role),
            'role': role,
            'has_mine': bool(self.sudo().search_count([('user_id', '=', user.id)])),
            'roles': [{'key': k, 'label': v} for k, v in ROLES],
            'catalogue': [{'key': k, 'label': v} for k, v in self._catalogue().items()],
            'boxes': [{'id': b.id, 'title': b.title or dict(b._fields['type']._description_selection(self.env))[b.type],
                       'report': b.report_id.name} for b in boxes],
            'can_save_role': user.has_group('marketing_intel.group_mi_manager'),
        }

    # ------------------------------------------------------------------ saving
    @api.model
    def choose_view(self, view):
        if view not in ('mine', *dict(ROLES)):
            raise UserError(_('Unknown view.'))
        self.env.user.sudo().mi_panel_view = view
        return True

    @api.model
    def save_layout(self, blocks, scope='mine', role=False):
        """Save the arrangement as my view, or (managers) as a role's shared view."""
        if not self.env.user.has_group('marketing_intel.group_mi_user'):
            raise AccessError(_('Only marketing users have a control panel.'))
        blocks = self._clean(blocks)
        if not blocks:
            raise UserError(_('Keep at least one block on the panel.'))
        if scope == 'role':
            if not self.env.user.has_group('marketing_intel.group_mi_manager'):
                raise AccessError(_('Only a marketing manager saves views for a role.'))
            if role not in dict(ROLES):
                raise UserError(_('Choose the role.'))
            layout = self._role_layout(role)
            values = {'blocks': blocks, 'name': dict(ROLES)[role]}
            if layout:
                layout.write(values)
            else:
                self.sudo().create(dict(values, role=role))
            self.env.user.sudo().mi_panel_view = role
            return True
        mine = self.sudo().search([('user_id', '=', self.env.uid)], limit=1)
        values = {'blocks': blocks, 'name': _('My view'), 'role': role or self._user_role()}
        if mine:
            mine.write(values)
        else:
            self.sudo().create(dict(values, user_id=self.env.uid))
        self.env.user.sudo().mi_panel_view = 'mine'
        return True

    @api.model
    def reset_mine(self):
        self.sudo().search([('user_id', '=', self.env.uid)]).unlink()
        self.env.user.sudo().mi_panel_view = False
        return True


class Users(models.Model):
    _inherit = 'res.users'

    mi_panel_view = fields.Selection([('mine', 'My view')] + ROLES, string='Marketing panel view')


class Panel(models.AbstractModel):
    _inherit = 'mi.panel'

    def _box_data(self, block):
        box = self.env['report.studio.block'].browse(block['report_block_id']).exists()
        if not box:
            return None
        try:
            box.check_access('read')
            box.report_id.check_access('read')
        except AccessError:
            return None
        data = box._safe_data()
        out = {'type': data['type'], 'title': data['title'] or box.report_id.name, 'report': box.report_id.name,
               'report_id': box.report_id.id, 'error': data.get('error') or '', 'display': data.get('display') or '',
               'text': data.get('text') or '', 'items': [str(i) for i in data.get('items') or []][:12],
               'columns': [str(c) for c in data.get('columns') or []],
               'rows': [[str(c) for c in row] for row in (data.get('rows') or [])[:10]], 'chart': None}
        chart = data.get('chart')
        if chart:
            top = max([abs(v) for v in chart['values']] or [1]) or 1
            out['chart'] = [{'label': str(label), 'value': value, 'pct': round(100 * abs(value) / top)}
                            for label, value in list(zip(chart['labels'], chart['values']))[:12]]
        if data['type'] == 'view':
            out['type'] = 'table' if data.get('rows') else ('chart' if out['chart'] else 'text')
        return out

    def _extra_blocks(self, keys, brands, plans):
        """Hook: data for blocks added by other modules, {key: data}."""
        return {}
