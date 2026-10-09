from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class WorkflowValue(models.Model):
    _name = 'workflow.value'
    _description = 'New Record Field'
    _order = 'id'
    step_id = fields.Many2one('workflow.step', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='step_id.company_id', store=True)
    target_model_id = fields.Many2one(related='step_id.create_model_id')
    source_model_id = fields.Many2one('ir.model', compute='_compute_source_model')
    _field_unique = models.Constraint('UNIQUE(step_id, field_id)', 'Set each target field only once.')

    @api.depends('step_id.kind', 'step_id.relation_field_id', 'step_id.model_id')
    def _compute_source_model(self):
        for mapping in self:
            step = mapping.step_id
            mapping.source_model_id = (
                self.env['ir.model']._get(step.relation_field_id.relation)
                if step.kind == 'foreach' and step.relation_field_id else step.model_id
            )

    field_id = fields.Many2one('ir.model.fields', string='Field to set', required=True, ondelete='cascade')
    field_type = fields.Selection(related='field_id.ttype')
    relation_model = fields.Char(related='field_id.relation')
    source = fields.Selection([('fixed', 'A fixed value'), ('field', 'A field from the source document'),
                               ('record', 'The source document itself')], default='fixed', required=True)
    source_field_id = fields.Many2one('ir.model.fields', string='Source field', ondelete='cascade')
    text_value = fields.Char(string='Text')
    number_value = fields.Float(string='Number')
    boolean_value = fields.Boolean(string='Yes')
    date_value = fields.Date(string='Date')
    datetime_value = fields.Datetime(string='Date and time')
    record_value = fields.Many2oneReference(model_field='relation_model', string='Related record')
    selection_value_id = fields.Many2one('ir.model.fields.selection', string='Option', ondelete='cascade')

    @api.model_create_multi
    def create(self, values):
        steps = self.env['workflow.step'].browse([v['step_id'] for v in values])
        steps.workflow_id._manager()
        steps.workflow_id._editable()
        records = super().create(values)
        steps.workflow_id.write({})
        return records

    def write(self, values):
        self.step_id.workflow_id._manager()
        self.step_id.workflow_id._editable()
        if 'step_id' in values:
            raise UserError(_('Field mappings cannot be moved between steps.'))
        result = super().write(values)
        self.step_id.workflow_id.write({})
        return result

    def unlink(self):
        workflows = self.step_id.workflow_id
        workflows._manager()
        workflows._editable()
        result = super().unlink()
        workflows.write({})
        return result

    def _validate_mapping(self):
        self.ensure_one()
        field = self.field_id
        if field.model_id != self.target_model_id or field.ttype not in (
            'char', 'text', 'html', 'integer', 'float', 'monetary', 'boolean', 'date', 'datetime', 'selection', 'many2one'
        ):
            raise ValidationError(_('Choose a supported field on the document being created.'))
        if self.source == 'fixed' and field.required:
            required_value = {
                'char': self.text_value, 'text': self.text_value, 'html': self.text_value,
                'date': self.date_value, 'datetime': self.datetime_value,
                'many2one': self.record_value, 'selection': self.selection_value_id.id,
            }.get(field.ttype, True)
            if not required_value:
                raise ValidationError(_('Enter a value for the required field %s.', field.field_description))
        if self.source == 'field':
            source = self.source_field_id
            compatible = source.ttype == field.ttype or {source.ttype, field.ttype} <= {'char', 'text', 'html'} or {source.ttype, field.ttype} <= {'float', 'monetary', 'integer'}
            if source.model_id != self.source_model_id or not compatible or (
                field.ttype == 'many2one' and source.relation != field.relation
            ):
                raise ValidationError(_('Choose a source field of the same type. Related records must use the same document type.'))
        elif self.source == 'record':
            if field.ttype != 'many2one' or field.relation != self.source_model_id.model:
                raise ValidationError(_('The target field must link to the source document type.'))
        elif field.ttype == 'selection' and self.selection_value_id.field_id != field:
            raise ValidationError(_('Choose an option for the selected field.'))

    def _value(self, record):
        self._validate_mapping()
        if self.source == 'record':
            return record.id
        if self.source == 'field':
            value = record[self.source_field_id.name]
            return value.id if self.field_type == 'many2one' else value
        if self.field_type == 'many2one':
            target = record.env[self.relation_model].browse(self.record_value).exists()
            target.check_access('read')
            return target.id
        return {
            'char': self.text_value, 'text': self.text_value, 'html': self.text_value,
            'integer': int(self.number_value), 'float': self.number_value,
            'monetary': self.number_value, 'boolean': self.boolean_value,
            'date': self.date_value, 'datetime': self.datetime_value,
            'selection': self.selection_value_id.value,
        }[self.field_type]
