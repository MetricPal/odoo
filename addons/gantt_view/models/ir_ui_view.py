from odoo import _, fields, models

GANTT_FIELD_ATTRS = ('date_start', 'date_stop', 'color', 'progress', 'dependency_field', 'default_group_by')


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    type = fields.Selection(selection_add=[('gantt', 'Gantt')])

    def _get_view_info(self):
        return {'gantt': {'icon': 'view_timeline'}} | super()._get_view_info()

    def _validate_tag_gantt(self, node, name_manager, node_info):
        """<gantt date_start="..." date_stop="..." [color] [progress] [dependency_field] [default_group_by]
        [default_scale="day|week|month|year"]>: the named fields must exist on the model."""
        if not node.get('date_start') or not node.get('date_stop'):
            self._raise_view_error(_('A <gantt> view needs date_start and date_stop.'), node)
        for attribute in GANTT_FIELD_ATTRS:
            for name in (node.get(attribute) or '').split(','):
                if name.strip():
                    name_manager.has_field(node, name.strip().split('.', 1)[0], node_info)
        scale = node.get('default_scale')
        if scale and scale not in ('day', 'week', 'month', 'year'):
            self._raise_view_error(_('default_scale must be day, week, month or year.'), node)
