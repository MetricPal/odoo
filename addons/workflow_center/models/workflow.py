import hashlib
import json
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

from odoo.addons.approval_center.models.common import capability

internal, trusted = capability('_workflow_token')


KINDS = [('action', 'Action'), ('condition', 'Condition'), ('branch', 'Branch'),
         ('wait', 'Wait'), ('foreach', 'For each record'), ('approval', 'Approval (optional)')]
ACTIONS = [('object_write', 'Update record'), ('object_create', 'Create record'),
           ('next_activity', 'Schedule activity'), ('followers', 'Add followers'),
           ('mail_post', 'Email or Odoo message'), ('webhook', 'Outgoing webhook'),
           ('code', 'Python code'), ('chat', 'Provider chat')]



def boolean_search_values(operator, value):
    """Booleans a search on a computed Boolean field asks for, or None if unsupported.

    Odoo 20 passes ``in``/``not in`` with a set of values (``= True`` becomes
    ``in {True}``); older callers may still pass ``=``/``!=``.
    """
    if operator in ('=', '!='):
        values = {bool(value)}
    elif operator in ('in', 'not in'):
        values = {bool(item) for item in value}
    else:
        return None
    if operator in ('!=', 'not in'):
        values = {True, False} - values
    return values

class Workflow(models.Model):
    _name = 'workflow.definition'
    _description = 'Workflow'
    _inherit = ['mail.thread']
    _order = 'write_date desc'

    name = fields.Char(required=True, default='New workflow')
    description = fields.Text()
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    user_id = fields.Many2one('res.users', string='Run as', required=True, default=lambda s: s.env.user)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        help='Managers of this department (and its sub-departments) who are Department workflow managers '
             'can see this workflow and its runs. They can preview, activate and pause it when it runs as them.')
    managed_by_me = fields.Boolean(compute='_compute_managed_by_me', search='_search_managed_by_me')
    model_id = fields.Many2one('ir.model', string='Document', required=True, ondelete='cascade',
                              domain=[('transient', '=', False)])
    model_name = fields.Char(related='model_id.model')
    trigger = fields.Selection([
        ('manual', 'Button / run manually'), ('create', 'Record created'),
        ('write', 'Record changed'), ('stage', 'Stage or status changed'),
        ('date', 'Date field'), ('schedule', 'Schedule'), ('webhook', 'Incoming webhook'),
    ], required=True, default='manual')
    trigger_field_id = fields.Many2one('ir.model.fields', string='Watch field', ondelete='cascade')
    date_field_id = fields.Many2one('ir.model.fields', string='Date field', ondelete='cascade')
    offset_days = fields.Integer(string='Days after date', default=0)
    interval_hours = fields.Integer(string='Repeat every (hours)', default=24)
    domain = fields.Char(string='Only when', default='[]', required=True)
    state = fields.Selection([('draft', 'Draft'), ('active', 'Active'), ('paused', 'Pause')],
                             default='draft', readonly=True, tracking=True, group_expand=True)
    revision = fields.Integer(default=1, readonly=True)
    tested_revision = fields.Integer(readonly=True)
    tested_digest = fields.Char(readonly=True)
    approved_by = fields.Many2one('res.users', readonly=True, tracking=True)
    approved_at = fields.Datetime(readonly=True)
    approved_digest = fields.Char(readonly=True, tracking=True)
    automation_id = fields.Many2one('base.automation', readonly=True, copy=False)
    manual_action_id = fields.Many2one('ir.actions.server', readonly=True, copy=False)
    next_run = fields.Datetime(readonly=True)
    schedule_cursor = fields.Integer(readonly=True)
    webhook_url = fields.Char(related='automation_id.url', string='Incoming webhook URL')
    step_ids = fields.One2many('workflow.step', 'workflow_id', copy=True)
    run_ids = fields.One2many('workflow.run', 'workflow_id')
    # Hidden copy behind a saved template: editable in the builder, never activated.
    is_template = fields.Boolean(readonly=True, copy=False, index=True)
    run_count = fields.Integer(compute='_compute_run_counts', string='Runs')
    failed_run_count = fields.Integer(compute='_compute_run_counts', string='Failed runs')
    last_run_at = fields.Datetime(compute='_compute_run_counts', string='Last run')
    ready_to_activate = fields.Boolean(compute='_compute_readiness')
    readiness_note = fields.Char(compute='_compute_readiness', string='Before activation')
    _protected = {'is_template', 'state', 'revision', 'tested_revision', 'approved_by', 'approved_at',
                  'approved_digest', 'automation_id', 'next_run', 'tested_digest', 'schedule_cursor', 'manual_action_id'}

    def _managed_department_ids(self):
        """Departments, with their sub-departments, that the current user manages in Employees."""
        departments = self.env['hr.department'].sudo().search(
            [('manager_id.user_id', '=', self.env.uid)])
        if not departments:
            return []
        return self.env['hr.department'].sudo().search([('id', 'child_of', departments.ids)]).ids

    @api.depends_context('uid')
    def _compute_managed_by_me(self):
        managed = set(self._managed_department_ids())
        for workflow in self:
            workflow.managed_by_me = workflow.sudo().department_id.id in managed

    def _search_managed_by_me(self, operator, value):
        values = boolean_search_values(operator, value)
        if values is None:
            return NotImplemented
        if values == {True, False}:
            return []
        if not values:
            return [('id', 'in', [])]
        managed = self._managed_department_ids()
        if True in values:
            return [('department_id', 'in', managed)]
        return ['|', ('department_id', '=', False), ('department_id', 'not in', managed)]

    def _is_department_manager(self):
        return self.env.user.has_group('workflow_center.group_workflow_department_manager')

    def _manager(self, operate=False):
        """Settings administrators configure and operate every workflow.

        With ``operate``, a Department workflow manager may also preview, activate
        and pause workflows of departments they manage that run as themselves.
        """
        if self.env.user.has_group('base.group_system'):
            self.check_access('write')
            return
        if operate and self and self._is_department_manager() and all(
            workflow.managed_by_me and workflow.sudo().user_id == self.env.user for workflow in self
        ):
            self.check_access('read')
            return
        raise AccessError(_('Only Settings administrators may change workflows. Department managers can '
                            'preview, activate and pause workflows of their department that run as them.'))

    def _viewer(self):
        """Read the builder: administrators, or department managers for their departments."""
        if self.env.user.has_group('base.group_system'):
            self.check_access('write')
            return
        if self and self._is_department_manager() and all(workflow.managed_by_me for workflow in self):
            self.check_access('read')
            return
        raise AccessError(_('This workflow belongs to another department.'))

    def _can_edit(self):
        return self.env.user.has_group('base.group_system')

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self) and any(self._protected & v.keys() for v in vals_list):
            raise AccessError(_('Use the workflow test and activation buttons.'))
        return super().create(vals_list)

    def write(self, vals):
        if not trusted(self):
            self._manager()
            if self._protected & vals.keys():
                raise AccessError(_('Use the workflow test and activation buttons.'))
            self._editable()
            result = super().write(vals)
            for workflow in self:
                internal(workflow).write({'revision': workflow.revision + 1, 'tested_revision': 0})
            return result
        return super().write(vals)

    def _editable(self):
        for workflow in self:
            self.env.cr.execute('SELECT id FROM workflow_definition WHERE id = %s FOR UPDATE', [workflow.id])
            workflow.invalidate_recordset()
            if workflow.state == 'active':
                raise UserError(_('Pause this workflow before changing it.'))
            if self.env['workflow.run'].search_count([
                ('workflow_id', '=', workflow.id), ('is_test', '=', False),
                ('state', 'in', ['running', 'waiting', 'failed']),
            ]):
                raise UserError(_('Stop unfinished runs before changing this workflow. Their steps must remain unchanged.'))

    def _not_template(self):
        if self.filtered('is_template'):
            raise UserError(_('This is a template. Start a workflow from it in Templates, then preview and '
                              'activate that workflow.'))

    def _compute_run_counts(self):
        Run = self.env['workflow.run'].sudo()
        live = [('workflow_id', 'in', self.ids), ('is_test', '=', False)]
        counts = {wf.id: n for wf, n in Run._read_group(live, ['workflow_id'], ['__count'])}
        failed = {wf.id: n for wf, n in Run._read_group(live + [('state', '=', 'failed')], ['workflow_id'], ['__count'])}
        last = {wf.id: at for wf, at in Run._read_group(live, ['workflow_id'], ['started_at:max'])}
        for workflow in self:
            workflow.run_count = counts.get(workflow.id, 0)
            workflow.failed_run_count = failed.get(workflow.id, 0)
            workflow.last_run_at = last.get(workflow.id, False)

    @api.depends_context('uid')
    def _compute_readiness(self):
        for workflow in self:
            workflow.ready_to_activate, workflow.readiness_note = False, ''
            if workflow.is_template or workflow.state == 'active' or not workflow.id:
                continue
            checked = workflow if workflow._can_edit() else workflow.sudo()
            issues = checked._validate()
            if issues:
                workflow.readiness_note = _('Needs setup: %s', issues[0])
            elif workflow.tested_revision != workflow.revision or workflow.tested_digest != checked._fingerprint():
                workflow.readiness_note = _('Preview it on a record first.')
            else:
                workflow.ready_to_activate = True

    # ------------------------------------------------------------------ copies

    def _clone(self, values=None, is_template=False):
        """A new draft with the same trigger and steps.

        Each step gets its own copy of its configured server action, and the
        Next / If-no links point to the new steps, so editing the copy never
        changes the original.
        """
        self.ensure_one()
        self._manager()
        source = self.sudo() if self._can_edit() else self
        fields_to_copy = ['name', 'description', 'company_id', 'user_id', 'department_id', 'model_id', 'trigger',
                          'trigger_field_id', 'date_field_id', 'offset_days', 'interval_hours', 'domain']
        vals = {}
        for name in fields_to_copy:
            value = source[name]
            vals[name] = value.id if isinstance(value, models.BaseModel) else value
        vals.update(values or {})
        new = self.create(vals)
        if is_template:
            internal(new).write({'is_template': True})
        mapping = {}
        Step = self.env['workflow.step']
        for step in source.step_ids.sorted('sequence'):
            action = step.action_id.copy({'name': step.action_id.name}) if step.action_id else step.action_id
            mapping[step] = step.copy({'workflow_id': new.id, 'name': step.name, 'next_id': False,
                                       'false_id': False, 'action_id': action.id})
        for old, copied in mapping.items():
            links = {}
            if old.next_id:
                links['next_id'] = mapping.get(old.next_id, Step).id
            if old.false_id:
                links['false_id'] = mapping.get(old.false_id, Step).id
            if links:
                copied.write(links)
        return new

    def action_duplicate(self):
        self.ensure_one()
        copy = self._clone({'name': _('%s (copy)', self.name)})
        return copy.action_open_builder()

    def action_save_as_template(self):
        self.ensure_one()
        self._manager()
        self._not_template()
        return {'type': 'ir.actions.act_window', 'res_model': 'workflow.template.save', 'view_mode': 'form',
                'views': [(False, 'form')], 'target': 'new', 'name': _('Save as template'),
                'context': {'default_workflow_id': self.id, 'default_name': self.name,
                            'default_description': self.description}}

    def action_run_history(self):
        self.ensure_one()
        self._viewer()
        action = self.env['ir.actions.act_window']._for_xml_id('workflow_center.action_run_history')
        action.update(domain=[('workflow_id', '=', self.id)], name=_('Runs: %s', self.name),
                      context={'search_default_live_runs': 1})
        return action

    def unlink(self):
        self._manager()
        self._editable()
        if self.run_ids:
            raise UserError(_('Keep workflows with run history for the audit trail. Pause them instead.'))
        self.automation_id.unlink()
        self.manual_action_id.unlink()
        return super().unlink()

    def _domain(self, text=None):
        domain = safe_eval(text if text is not None else self.domain, {})
        if not isinstance(domain, list):
            raise ValidationError(_('Choose a valid record filter.'))
        return domain

    def _fingerprint(self):
        self.ensure_one()
        payload = [self.name, self.model_name, self.company_id.id, self.user_id.id, self.trigger,
                   self.trigger_field_id.id, self.date_field_id.id, self.offset_days,
                   self.interval_hours, self.domain]
        for step in self.step_ids.sorted('sequence'):
            action = step.action_id
            config_names = {
                'name', 'model_id', 'state', 'code', 'crud_model_id', 'link_field_id',
                'group_ids', 'update_field_id', 'update_property', 'update_path',
                'update_related_model_id', 'update_m2m_operation', 'update_boolean_value',
                'value', 'evaluation_type', 'html_value', 'sequence_id', 'resource_ref',
                'selection_value', 'property_selection', 'webhook_url', 'webhook_field_ids',
                'followers_type', 'followers_partner_field_name', 'partner_ids',
                'subtype_ids', 'template_id', 'mail_post_autofollow',
            }
            config_names.update(name for name in action._fields
                                if name.startswith('activity_') and name != 'activity_ids')
            values = action.sudo().read(sorted(name for name in config_names
                                        if name in action._fields and action._fields[name].store)) if action else []
            values.append({
                'create_model': step.create_model_id.id, 'link_field': step.created_link_field_id.id,
                'mappings': step.value_ids.read(['field_id', 'source', 'source_field_id',
                    'text_value', 'number_value', 'boolean_value', 'date_value',
                    'datetime_value', 'record_value', 'selection_value_id']),
            })
            if action.template_id:
                values.append(action.template_id.sudo().read([name for name in (
                    'subject', 'body_html', 'email_from', 'email_to', 'partner_to', 'email_cc',
                    'reply_to', 'scheduled_date', 'mail_server_id', 'use_default_to',
                ) if name in action.template_id._fields]))
            payload.append([step.id, step.name, step.kind, step.action_type, step.domain,
                            step.wait_hours, step.wait_date_id.name, step.next_id.id,
                            step.false_id.id, step.end, step.policy_id.id,
                            step.relation_field_id.name, step.on_error, step.max_attempts, values])
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def _validate(self):
        self.ensure_one()
        issues = []
        if self.user_id.share or not self.user_id.active or self.user_id.id == 1:
            issues.append(_('Choose an active internal execution user (not the superuser).'))
        if self.company_id not in self.user_id.company_ids:
            issues.append(_('The execution user needs access to this company.'))
        if self.model_name.startswith(('ir.', 'workflow.', 'res.users', 'res.groups')):
            issues.append(_('Choose a business document rather than a system configuration model.'))
        try:
            self.env[self.model_name].with_user(self.user_id).with_company(self.company_id).search(
                self._domain(), limit=1)
        except Exception:
            issues.append(_('The record filter or execution user access is invalid.'))
        if not self.step_ids:
            issues.append(_('Add at least one step.'))
        if self.trigger in ('write', 'stage') and not self.trigger_field_id:
            issues.append(_('Choose the field to watch for changes.'))
        if self.trigger_field_id and self.trigger_field_id.model != self.model_name:
            issues.append(_('The watched field must belong to the selected document.'))
        if self.trigger == 'date' and (
            not self.date_field_id or self.date_field_id.model != self.model_name
            or self.date_field_id.ttype not in ('date', 'datetime')
        ):
            issues.append(_('Choose a date field on this document.'))
        if self.interval_hours < 1:
            issues.append(_('The schedule interval must be at least one hour.'))
        for step in self.step_ids:
            issues += step._issues()
        # The graph is finite. Loops belong in the bounded "for each" action.
        visiting, visited = set(), set()
        def visit(step):
            if not step or step.id in visited:
                return
            if step.id in visiting:
                raise ValidationError(_('Steps contain a cycle. Use a For each record step for a bounded loop.'))
            visiting.add(step.id)
            visit(step._next())
            if step.kind == 'branch':
                visit(step.false_id)
            visiting.remove(step.id)
            visited.add(step.id)
        if self.step_ids:
            try:
                visit(self.step_ids.sorted('sequence')[:1])
            except ValidationError as exc:
                issues.append(str(exc))
            if len(visited) != len(self.step_ids):
                issues.append(_('Some steps are not connected to the trigger, or the paths contain a cycle. Review the canvas.'))
        return issues

    def action_activate(self):
        self.ensure_one()
        self._manager(operate=True)
        self._not_template()
        # Validation reads technical records (server actions, fields) that only
        # administrators may read; after the check above it runs privileged.
        checked = self if self._can_edit() else self.sudo()
        issues = checked._validate()
        if issues:
            raise UserError('\n'.join(issues))
        if self.tested_revision != self.revision or self.tested_digest != checked._fingerprint():
            raise UserError(_('Run a preview on a record before activating this version.'))
        digest = checked._fingerprint()
        internal(checked).write({'state': 'active', 'approved_by': self.env.uid,
                              'approved_at': fields.Datetime.now(), 'approved_digest': digest,
                              'schedule_cursor': 0, 'next_run': fields.Datetime.now() + timedelta(hours=self.interval_hours)})
        # The generated rules contain fixed module code only, so installing them
        # for a department manager after the checks above is safe.
        self.sudo()._install_trigger()
        self.env.ref('workflow_center.cron_workflows').sudo().write({'active': True})
        return True

    def action_pause(self):
        self._manager(operate=True)
        self.sudo().automation_id.write({'active': False})
        self.sudo().manual_action_id.write({'binding_model_id': False})
        internal(self if self._can_edit() else self.sudo()).write({'state': 'paused'})
        return True

    def _install_trigger(self):
        self.ensure_one()
        if self.trigger == 'manual':
            values = {
                'name': _('Run workflow: %s', self.name), 'model_id': self.model_id.id,
                'binding_model_id': self.model_id.id, 'binding_type': 'action', 'state': 'code',
                'group_ids': [fields.Command.set(self.env.ref('base.group_user').ids)],
                'code': (
                    "records.check_access('write')\n"
                    f"workflow = env['workflow.definition'].sudo().browse({self.id})\n"
                    "if workflow.company_id not in env.companies:\n"
                    "    raise UserError('Switch to the workflow company before running it.')\n"
                    "workflow._trigger_records(records)"
                ),
            }
            if self.manual_action_id:
                self.manual_action_id.write(values)
            else:
                internal(self).write({'manual_action_id': self.env['ir.actions.server'].create(values).id})
            return
        if self.trigger == 'schedule':
            return
        trigger = {'create': 'on_create', 'write': 'on_write', 'stage': 'on_write',
                   'date': 'on_time', 'webhook': 'on_webhook'}[self.trigger]
        values = {'name': self.name, 'model_id': self.model_id.id, 'trigger': trigger,
                  'active': True, 'filter_domain': self.domain}
        if self.trigger_field_id:
            values['trigger_field_ids'] = [fields.Command.set(self.trigger_field_id.ids)]
        if self.trigger == 'date':
            values.update(trg_date_id=self.date_field_id.id, trg_date_range=abs(self.offset_days),
                          trg_date_range_mode='before' if self.offset_days < 0 else 'after',
                          trg_date_range_type='day')
        if self.trigger == 'webhook':
            values['record_getter'] = f"model.env[{self.model_name!r}].browse(int(payload.get('_id', 0)))"
        if self.automation_id:
            self.automation_id.write(values)
        else:
            automation = self.env['base.automation'].create(values)
            action = self.env['ir.actions.server'].create({
                'name': self.name, 'model_id': self.model_id.id, 'state': 'code',
                'base_automation_id': automation.id,
                'code': f"env['workflow.definition'].browse({self.id})._trigger_records(records)",
            })
            automation.action_server_ids = action
            internal(self).write({'automation_id': automation.id})

    def _trigger_records(self, records):
        self.ensure_one()
        if self.state != 'active' or self.env.context.get('workflow_executing'):
            return
        self.env.cr.execute('SELECT id FROM workflow_definition WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()
        if self.state != 'active':
            return
        workflow = self.sudo()
        records = records.with_user(self.user_id).with_context(
            allowed_company_ids=[self.company_id.id], workflow_executing=True).with_company(self.company_id)
        for record in records:
            if not record.has_access('read'):
                if self.trigger == 'manual':
                    record.check_access('read')  # explicit run: tell the user why
                # Automatic events run inside the editing user's transaction:
                # never fail their save because the run-as user cannot read
                # this record. Skip it instead.
                continue
            if 'company_id' in record and record.company_id and record.company_id != self.company_id:
                continue
            if not record.filtered_domain(workflow._domain()):
                continue
            running = self.env['workflow.run'].sudo().search_count([
                ('workflow_id', '=', self.id), ('record_id', '=', record.id),
                ('is_test', '=', False), ('state', 'in', ['running', 'waiting', 'failed']),
            ])
            if not running:
                run = internal(workflow.env['workflow.run'].sudo()).create({
                    'workflow_id': self.id, 'record_id': record.id,
                    'name': record.display_name, 'revision': self.revision,
                    'step_id': self.step_ids.sorted('sequence')[:1].id,
                })
                run._log(_('Queued for the workflow worker.'), 'queued')
        return True

    def action_test_dialog(self):
        self.ensure_one()
        self._manager(operate=True)
        self._not_template()
        return {'type': 'ir.actions.act_window', 'res_model': 'workflow.test',
                'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new', 'name': _('Test or run workflow'),
                'context': {'default_workflow_id': self.id}}

    @api.model
    def home_data(self):
        self._manager()
        from .templates import catalog
        templates = catalog()
        for index, item in enumerate(templates, 1):
            item['id'] = index
            item['model_name'] = item['model']
            item['display_name'] = item['name']
            item['available'] = item['model'] in self.env
        return {
            'templates': templates,
            'workflows': self.search_read([('is_template', '=', False)], ['name', 'state', 'model_id', 'trigger', 'description']),
            'models': self.env['ir.model'].search_read(
                [('transient', '=', False), ('abstract', '=', False), ('model', 'not like', 'ir.%'),
                 ('model', 'not like', 'workflow.%'), ('model', 'not in', ['res.users', 'res.groups'])],
                ['name', 'model'], order='name'),
        }

    def _builder_ai_info(self):
        """AI drafting status for the builder; extended by the AI Agent bridge."""
        return False

    def action_open_builder(self):
        self.ensure_one()
        self._viewer()
        return {'type': 'ir.actions.client', 'tag': 'workflow_center.builder',
                'name': self.name, 'params': {'workflow_id': self.id}}

    def builder_data(self):
        self.ensure_one()
        self._viewer()
        data = self.read(['name', 'description', 'model_id', 'trigger', 'domain', 'state',
                          'revision', 'tested_revision', 'webhook_url', 'is_template'])[0]
        data['ai'] = self._builder_ai_info()
        data['can_edit'] = self._can_edit()
        data['steps'] = self.step_ids.sorted('sequence').read([
            'name', 'kind', 'action_type', 'sequence', 'on_error', 'next_id', 'false_id', 'end',
            'action_id', 'wait_hours', 'wait_date_id', 'policy_id', 'domain'])
        checked = self if self._can_edit() else self.sudo()
        data['issues'] = checked._validate()
        data['preview_current'] = self.tested_revision == self.revision and self.tested_digest == checked._fingerprint()
        return data

    def add_step(self, kind, action_type='object_write', after_id=False):
        self.ensure_one()
        self._manager()
        self._editable()
        after = self.step_ids.filtered(lambda s: s.id == after_id)
        position = after.sequence + 1 if after else 0
        for step in self.step_ids.filtered(lambda s: s.sequence >= position):
            step.sequence += 1
        label = dict(ACTIONS).get(action_type) if kind == 'action' else dict(KINDS).get(kind)
        step = self.env['workflow.step'].create({
            'workflow_id': self.id, 'name': label or _('New step'),
            'kind': kind, 'action_type': action_type, 'sequence': position,
        })
        if after and after.end:
            after.end = False
            step.end = True
        if after and after.next_id:
            step.next_id = after.next_id
            after.next_id = step
        return step.id

    @api.model
    def from_template(self, key):
        self._manager()
        from .templates import create_template
        return create_template(self, key).id


class Step(models.Model):
    _name = 'workflow.step'
    _description = 'Workflow Step'
    _order = 'sequence, id'

    workflow_id = fields.Many2one('workflow.definition', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='workflow_id.company_id', store=True)
    model_name = fields.Char(related='workflow_id.model_name')
    model_id = fields.Many2one(related='workflow_id.model_id')
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection(KINDS, required=True, default='action')
    action_type = fields.Selection(ACTIONS, default='object_write', required=True)
    create_model_id = fields.Many2one('ir.model', string='Document to create', ondelete='cascade')
    value_ids = fields.One2many('workflow.value', 'step_id', string='Fields to set', copy=True)
    created_link_field_id = fields.Many2one('ir.model.fields', string='Save the new record in', ondelete='cascade')
    action_id = fields.Many2one('ir.actions.server', string='Configured action', ondelete='restrict')
    domain = fields.Char(string='Matching records', default='[]')
    wait_hours = fields.Float(string='Wait (hours)', default=24)
    wait_date_id = fields.Many2one('ir.model.fields', string='Or wait until date field', ondelete='cascade')
    relation_field_id = fields.Many2one('ir.model.fields', string='Related records', ondelete='cascade')
    policy_id = fields.Many2one('approval.center.policy', string='Approval type', ondelete='restrict')
    on_error = fields.Selection([('stop', 'Stop and show the error'), ('retry', 'Retry, then stop'),
                                 ('continue', 'Log error and continue')], default='stop', required=True)
    max_attempts = fields.Integer(default=3, string='Maximum attempts')
    next_id = fields.Many2one('workflow.step', string='Next / if yes', ondelete='restrict')
    false_id = fields.Many2one('workflow.step', string='If no', ondelete='restrict')
    end = fields.Boolean(string='End this path after this step')

    @api.model_create_multi
    def create(self, vals_list):
        workflows = self.env['workflow.definition'].browse([v['workflow_id'] for v in vals_list])
        workflows._manager()
        workflows._editable()
        result = super().create(vals_list)
        workflows.write({})
        return result

    def write(self, vals):
        self.workflow_id._manager()
        self.workflow_id._editable()
        if 'workflow_id' in vals:
            raise UserError(_('Steps cannot be moved between workflows.'))
        result = super().write(vals)
        self.workflow_id.write({})
        return result

    def unlink(self):
        workflows = self.workflow_id
        workflows._manager()
        workflows._editable()
        result = super().unlink()
        workflows.write({})
        return result

    def _next(self):
        self.ensure_one()
        if self.end:
            return self.browse()
        if self.next_id:
            return self.next_id
        return self.workflow_id.step_ids.filtered(lambda s: s.sequence > self.sequence).sorted('sequence')[:1]

    def _issues(self):
        self.ensure_one()
        problems = []
        for edge in (self.next_id, self.false_id):
            if edge and edge.workflow_id != self.workflow_id:
                problems.append(_('Choose the next step from this workflow.'))
        if self.kind == 'branch' and not self.false_id:
            problems.append(_('%s: choose the “If no” step.', self.name))
        if self.kind in ('condition', 'branch'):
            if not self.domain or self.domain.strip() == '[]':
                problems.append(_('%s: choose the condition to check.', self.name))
            try:
                self.env[self.model_name].search(self.workflow_id._domain(self.domain), limit=1)
            except Exception:
                problems.append(_('%s: set a valid condition.', self.name))
        if self.kind in ('action', 'foreach'):
            if self.action_type == 'object_create':
                if not self.create_model_id or not self.value_ids:
                    problems.append(_('%s: choose the document to create and fill in its fields.', self.name))
                elif self.create_model_id.model.startswith(('ir.', 'workflow.', 'res.users', 'res.groups')):
                    problems.append(_('%s: choose a business document to create.', self.name))
                else:
                    try:
                        for mapping in self.value_ids:
                            mapping._validate_mapping()
                        target = self.env[self.create_model_id.model].with_user(self.workflow_id.user_id)
                        required = [name for name, field in target._fields.items()
                                    if field.required and not field.compute and not field.readonly]
                        defaults = target.with_company(self.company_id).default_get(required)
                        configured = set(self.value_ids.field_id.mapped('name'))
                        missing = [target._fields[name].string for name in required
                                   if name not in configured and not defaults.get(name)]
                        if missing:
                            problems.append(_('%s: set required fields: %s', self.name, ', '.join(missing)))
                    except (UserError, AccessError, ValidationError) as exc:
                        problems.append(_('%s: %s', self.name, str(exc)))
                if self.created_link_field_id and (
                    self.created_link_field_id.model != self.model_name
                    or self.created_link_field_id.ttype != 'many2one'
                    or self.created_link_field_id.relation != self.create_model_id.model
                ):
                    problems.append(_('%s: choose a source field that links to the new document.', self.name))
            elif self.action_type == 'chat':
                problems.append(_('%s: provider chat needs an installed workflow provider integration. Use email or an Odoo message for now.', self.name))
            elif not self.action_id:
                problems.append(_('%s: configure what this action will do.', self.name))
            elif self.action_id.state != self.action_type:
                problems.append(_('%s: the action type does not match its configuration.', self.name))
            elif self.kind == 'action' and self.action_id.model_id != self.model_id:
                problems.append(_('%s: choose an action for this document.', self.name))
            if self.action_id and self.action_type != 'object_create':
                action = self.action_id
                problems.extend(_('%s: %s', self.name, warning) for warning in action._get_warning_messages())
                if action.state == 'object_write' and not action.update_path:
                    problems.append(_('%s: choose the field to update.', self.name))
                if action.state == 'object_create' and not action.crud_model_id:
                    problems.append(_('%s: choose the document to create.', self.name))
                if action.state == 'mail_post' and not action.template_id:
                    problems.append(_('%s: choose a message template.', self.name))
                if action.state == 'code' and not self.workflow_id.user_id.has_group('base.group_system'):
                    problems.append(_('%s: Python code requires a Settings administrator as the execution user.', self.name))
                if action.state == 'code' and not any(
                    line.strip() and not line.strip().startswith('#') for line in (action.code or '').splitlines()
                ):
                    problems.append(_('%s: configure the Python action.', self.name))
            if self.action_type == 'webhook' and self.action_id:
                from .execution import webhook_target
                try:
                    webhook_target(self.action_id.webhook_url, resolve=False)
                except UserError as exc:
                    problems.append(_('%s: %s', self.name, str(exc)))
        if self.kind == 'foreach':
            f = self.relation_field_id
            if not f or f.model != self.model_name or f.ttype not in ('one2many', 'many2many'):
                problems.append(_('%s: choose a related-record list.', self.name))
            elif self.action_id and self.action_id.model_name != f.relation:
                problems.append(_('%s: the action must apply to the related document.', self.name))
        if self.kind == 'wait' and self.wait_hours <= 0 and not self.wait_date_id:
            problems.append(_('%s: choose a positive wait duration or a date field.', self.name))
        if self.wait_date_id and (self.wait_date_id.model != self.model_name or self.wait_date_id.ttype not in ('date', 'datetime')):
            problems.append(_('%s: choose a date field on this document.', self.name))
        if self.kind == 'approval' and self.policy_id:
            commands = self.env['approval.center.request']._get_approval_type_approver_commands(
                self.policy_id, self.workflow_id.user_id)
            eligible = [command[2]['user_id'] for command in commands
                        if command[2]['user_id'] != self.workflow_id.user_id.id]
            if len(set(eligible)) < self.policy_id.approval_minimum:
                problems.append(_('%s: configure enough approvers other than the execution user.', self.name))
            unsupported = [self.policy_id._fields[name].string for name in (
                'has_document', 'has_date', 'has_period', 'has_items', 'has_quantity', 'has_payment', 'has_location'
            ) if self.policy_id[name] == 'required']
            source = self.env[self.model_name]
            if self.policy_id.has_amount == 'required' and not any(name in source._fields for name in ('amount_total', 'amount')):
                unsupported.append(_('Amount'))
            if self.policy_id.has_partner == 'required' and 'partner_id' not in source._fields:
                unsupported.append(_('Contact'))
            if unsupported:
                problems.append(_('%s: this approval type requires information the workflow does not supply: %s. Use a review-only approval type.', self.name, ', '.join(unsupported)))
        if self.kind == 'approval' and (not self.policy_id or not self.policy_id.active):
            problems.append(_('%s: choose an active approval type.', self.name))
        if self.policy_id.company_id and self.policy_id.company_id != self.company_id:
            problems.append(_('%s: choose an approval type in this company.', self.name))
        if self.policy_id and (self.policy_id.action_name or self.policy_id.model not in (False, self.model_name)):
            problems.append(_('%s: use a review-only approval type for this document. The next workflow step performs the action.', self.name))
        if not 1 <= self.max_attempts <= 10:
            problems.append(_('%s: use between 1 and 10 attempts.', self.name))
        return problems

    def action_configure(self):
        self.ensure_one()
        self.workflow_id._manager()
        self.workflow_id._editable()
        if self.action_type == 'chat':
            raise UserError(_('Provider chat integration is not installed. Choose email or an Odoo message, or leave this draft for later.'))
        if not self.action_id:
            model = self.model_id
            if self.kind == 'foreach':
                if not self.relation_field_id:
                    raise UserError(_('Choose the related records first.'))
                model = self.env['ir.model']._get(self.relation_field_id.relation)
            self.action_id = self.env['ir.actions.server'].create({
                'name': self.name, 'model_id': model.id, 'state': self.action_type})
        return {'type': 'ir.actions.act_window', 'res_model': 'ir.actions.server',
                'res_id': self.action_id.id, 'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new',
                'name': _('Configure action')}
