import hashlib
import ipaddress
import json
import os
import socket
from datetime import timedelta
from urllib.parse import urlsplit

import urllib3

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .workflow import internal, trusted


def webhook_target(url, resolve=True):
    try:
        target = urlsplit(url or '')
        port = target.port
    except ValueError:
        raise UserError(_('Enter a valid HTTPS webhook URL.')) from None
    allowed = {h.strip().lower() for h in os.environ.get('WORKFLOW_WEBHOOK_HOSTS', '').split(',') if h.strip()}
    if (target.scheme != 'https' or not target.hostname or target.username or target.password
            or target.fragment or port not in (None, 443) or target.hostname.lower() not in allowed):
        raise UserError(_('Use an HTTPS URL on a host listed in WORKFLOW_WEBHOOK_HOSTS by your deployment administrator.'))
    addresses = []
    if resolve:
        addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(target.hostname, 443, type=socket.SOCK_STREAM)})
        if not addresses or any((not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast) for ip in addresses):
            raise UserError(_('The webhook must resolve only to public addresses.'))
    return target, addresses


class DeliveryUncertain(UserError):
    pass


class WorkflowRun(models.Model):
    _name = 'workflow.run'
    _description = 'Workflow Run'
    _order = 'id desc'

    workflow_id = fields.Many2one('workflow.definition', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='workflow_id.company_id', store=True)
    name = fields.Char(string='Record', required=True)
    record_id = fields.Integer(string='Source record ID', required=True)
    revision = fields.Integer(required=True)
    state = fields.Selection([('running', 'Running'), ('waiting', 'Waiting'), ('failed', 'Failed'),
                              ('done', 'Done'), ('stopped', 'Stopped')], default='running', required=True)
    is_test = fields.Boolean(string='Preview only')
    step_id = fields.Many2one('workflow.step', ondelete='restrict', string='Current step')
    step_kind = fields.Selection(related='step_id.kind')
    wake_at = fields.Datetime()
    error = fields.Text()
    delivery_unknown = fields.Boolean()
    approval_record_digest = fields.Char()
    approval_id = fields.Many2one('approval.center.request', ondelete='restrict')
    log_ids = fields.One2many('workflow.run.log', 'run_id')
    started_at = fields.Datetime(default=fields.Datetime.now)
    finished_at = fields.Datetime()
    attempts = fields.Integer()
    run_key = fields.Char()
    _key_unique = models.Constraint('UNIQUE(run_key)', 'This scheduled event already has a run.')

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self):
            raise AccessError(_('Runs are created by the workflow engine.'))
        return super().create(vals_list)

    def write(self, values):
        if not trusted(self):
            raise AccessError(_('Use the run controls; history cannot be edited.'))
        return super().write(values)

    def unlink(self):
        raise AccessError(_('Workflow run history cannot be deleted.'))

    def _set(self, **values):
        internal(self).write(values)

    def _log(self, message, status='done', step=None):
        internal(self.env['workflow.run.log'].sudo()).create({
            'run_id': self.id, 'name': (step or self.step_id).name or _('Workflow'),
            'message': message, 'state': status, 'actor_id': self.env.uid,
        })

    def _record(self):
        workflow = self.workflow_id
        if not workflow.user_id.active or workflow.user_id.share:
            raise AccessError(_('The execution user is inactive or is no longer an internal user.'))
        record = self.env[workflow.model_name].with_user(workflow.user_id).with_context(
            allowed_company_ids=[workflow.company_id.id], workflow_executing=True, _workflow_token=None).with_company(
            workflow.company_id).browse(self.record_id).exists()
        if not record:
            raise UserError(_('The source record no longer exists.'))
        record.check_access('read')
        if 'company_id' in record and record.company_id and record.company_id != workflow.company_id:
            raise AccessError(_('The record belongs to another company.'))
        return record

    def _advance(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM workflow_run WHERE id = %s FOR UPDATE SKIP LOCKED', [self.id])
        if not self.env.cr.fetchone():
            return
        self.invalidate_recordset()
        workflow = self.workflow_id
        if self.is_test or self.state not in ('running', 'waiting') or workflow.state != 'active':
            return
        executing_action = False
        try:
            if self.revision != workflow.revision or workflow._fingerprint() != workflow.approved_digest:
                raise UserError(_('The approved configuration changed. Stop this run, review the workflow and activate it again.'))
            record = self._record()
            if self.state == 'waiting':
                if self.approval_id:
                    if self.approval_id.state == 'refused':
                        self._set(state='stopped', finished_at=fields.Datetime.now())
                        self._log(_('Approval was refused.'), 'stopped')
                        return
                    if self.approval_id.state != 'approved':
                        return
                    if self.approval_record_digest != self._record_digest(record):
                        raise UserError(_('The record changed while approval was pending. Stop this run and request a fresh review before continuing.'))
                    self._log(_('Approval received.'))
                elif self.wake_at and self.wake_at > fields.Datetime.now():
                    return
                if self.step_id.kind in ('wait', 'approval'):
                    self._set(step_id=self.step_id._next().id, attempts=0)
                self._set(state='running', wake_at=False, approval_id=False)
            for _index in range(100):
                step = self.step_id
                if not step:
                    self._set(state='done', finished_at=fields.Datetime.now())
                    return
                self._set(attempts=self.attempts + 1, error=False)
                next_step = step._next()
                if step.kind in ('condition', 'branch'):
                    matched = bool(record.filtered_domain(workflow._domain(step.domain)))
                    self._log(_('Condition matched.') if matched else _('Condition did not match.'))
                    if not matched:
                        next_step = step.false_id if step.kind == 'branch' else step.browse()
                elif step.kind == 'wait':
                    if step.wait_date_id and not record[step.wait_date_id.name]:
                        raise UserError(_('Set %s on this record before continuing the wait.', step.wait_date_id.field_description))
                    when = (fields.Datetime.to_datetime(record[step.wait_date_id.name])
                            if step.wait_date_id else fields.Datetime.now() + timedelta(hours=step.wait_hours))
                    self._set(state='waiting', wake_at=when)
                    self._log(_('Waiting until %s.', when), 'waiting')
                    return
                elif step.kind == 'approval':
                    with self.env.cr.savepoint():
                        request = internal(record.env['approval.center.request']).create({
                            'workflow_run_id': self.id, 'workflow_minimum': step.policy_id.approval_minimum,
                            'workflow_sequential': step.policy_id.approver_sequence,
                            'name': f'{workflow.name}: {record.display_name}',
                            'policy_id': step.policy_id.id, 'company_id': workflow.company_id.id,
                            'reference': record.display_name,
                            'partner_id': record.partner_id.id if 'partner_id' in record else False,
                            'amount': self._approval_amount(record),
                            'target_model': record._name, 'target_res_id': record.id,
                            'reason': _('Workflow: %(workflow)s. Step: %(step)s. Review this record before the workflow continues.',
                                        workflow=workflow.name, step=step.name),
                        })
                        request.action_submit()
                    self._set(state='waiting', approval_id=request.id, approval_record_digest=self._record_digest(record))
                    self._log(_('Waiting for the approvers configured on %s.', step.policy_id.name), 'waiting')
                    return
                else:
                    executing_action = True
                    with self.env.cr.savepoint():
                        targets = record
                        if step.kind == 'foreach':
                            targets = record[step.relation_field_id.name]
                            if len(targets) > 500:
                                raise UserError(_('This loop has more than 500 records. Reduce its scope.'))
                        for target in targets:
                            target.check_access('read')
                            if 'company_id' in target and target.company_id and target.company_id != workflow.company_id:
                                raise AccessError(_('A related record belongs to another company.'))
                            self._execute(step, target)
                    executing_action = False
                    self._log(_('Message handed to Odoo for processing. Check Email delivery in Technical settings.') if step.action_type == 'mail_post' else _('Action completed.'))
                self._set(step_id=next_step.id, attempts=0, delivery_unknown=False)
            raise UserError(_('This run exceeded the step limit.'))
        except Exception as exc:
            # Native DB operations are rolled back at the per-step savepoint.
            # Remote calls are never blindly retried after an uncertain outcome.
            message = str(exc)[:2000]
            step = self.step_id
            self._set(state='failed', error=message, delivery_unknown=isinstance(exc, DeliveryUncertain) or bool(executing_action and self.step_id and self.step_id.action_type == 'code'))
            self._log(message, 'failed')
            if executing_action and step and step.kind in ('action', 'foreach') and not self.delivery_unknown and isinstance(exc, UserError):
                if step.on_error == 'retry' and self.attempts < step.max_attempts:
                    self._set(state='waiting', wake_at=fields.Datetime.now() + timedelta(minutes=5))
                elif step.on_error == 'continue':
                    self._log(_('Configured failure rule: skipped this action.'), 'skipped')
                    self._set(step_id=step._next().id, state='running', attempts=0)

    def _record_digest(self, record):
        readable = record.fields_get()
        names = [name for name, field in record._fields.items()
                 if name in readable and field.store and field.type != 'binary'
                 and name not in ('message_ids', 'message_follower_ids', 'activity_ids')]
        values = record.read(names, load=None)
        lines = {}
        for name in names:
            if record._fields[name].type == 'one2many':
                children = record[name]
                if children and children._log_access:
                    lines[name] = children.read(['write_date'], load=None)
        return hashlib.sha256(json.dumps([values, lines], sort_keys=True, default=str).encode()).hexdigest()

    def _approval_amount(self, record):
        amount = record.amount_total if 'amount_total' in record else record.amount if 'amount' in record else 0
        currency = record.currency_id if 'currency_id' in record else self.company_id.currency_id
        if currency and currency != self.company_id.currency_id:
            amount = currency._convert(amount, self.company_id.currency_id, self.company_id, fields.Date.today())
        return amount

    def _execute(self, step, record):
        if step.action_type == 'object_create':
            values = {mapping.field_id.name: mapping._value(record) for mapping in step.value_ids}
            created = record.env[step.create_model_id.model].create(values)
            if 'company_id' in created and created.company_id and created.company_id != self.company_id:
                raise AccessError(_('The created record must belong to the workflow company.'))
            if step.created_link_field_id:
                record.write({step.created_link_field_id.name: created.id})
            return
        action = step.action_id.with_env(record.env)
        if step.action_type != 'webhook':
            action = action.with_context(active_model=record._name, active_id=record.id, active_ids=record.ids)
            action._can_execute_action_on_records(record)
            # Native run() elevates the runner itself. Retain the native dispatch
            # and validation while keeping business writes in the approved user's environment.
            context = action._get_eval_context(action.sudo())
            action._run(record, context)
            return
        target, addresses = webhook_target(action.webhook_url)
        payload = {'_model': record._name, '_id': record.id,
                   **record.read(action.webhook_field_ids.mapped('name'), load=None)[0]}
        # Bind the connection to the validated IP, retaining TLS hostname validation.
        pool = urllib3.HTTPSConnectionPool(
            addresses[0], port=443, assert_hostname=target.hostname,
            server_hostname=target.hostname, timeout=urllib3.Timeout(connect=5, read=15),
            retries=False,
        )
        try:
            response = pool.request(
                'POST', target.path + ('?' + target.query if target.query else '') or '/',
                body=json.dumps(payload, default=str).encode(),
                headers={'Host': target.hostname, 'Content-Type': 'application/json',
                         'Idempotency-Key': f'workflow-{self.env.cr.dbname}-{self.id}-{step.id}-{record.id}'},
                redirect=False, preload_content=False,
            )
            status = response.status
            response.release_conn()
            if not 200 <= status < 300:
                # Even a 503 can follow a remote side effect; require reconciliation.
                raise DeliveryUncertain(_('Webhook returned HTTP %s. Check delivery at the destination before retrying.', status))
        except (urllib3.exceptions.HTTPError, OSError):
            raise DeliveryUncertain(_('Webhook delivery could not be confirmed. Check the destination before retrying.')) from None
        finally:
            pool.close()

    def _operate(self):
        self.ensure_one()
        self.workflow_id._manager()
        if self.is_test:
            raise UserError(_('Preview runs cannot be executed.'))
        self.env.cr.execute('SELECT id FROM workflow_run WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    def _require_active(self):
        if self.workflow_id.state != 'active':
            raise UserError(_('Activate the reviewed workflow before retrying or continuing a run.'))

    def action_retry(self):
        self._operate()
        self._require_active()
        if self.state != 'failed':
            raise UserError(_('Only failed runs can be retried.'))
        if self.delivery_unknown:
            raise UserError(_('Delivery is uncertain. Use “Retry after checking delivery” only after confirming the destination did not process it.'))
        self._log(_('Administrator requested a retry.'), 'retry')
        self._set(state='running')
        self._advance()

    def action_retry_confirmed(self):
        self._operate()
        self._require_active()
        if self.state != 'failed' or not self.delivery_unknown:
            raise UserError(_('This control is only for uncertain deliveries.'))
        self._log(_('Administrator confirmed the destination did not process this delivery and authorized retry.'), 'retry')
        self._set(delivery_unknown=False, state='running')
        self._advance()

    def action_skip(self):
        self._operate()
        self._require_active()
        if self.state != 'failed' or self.step_id.kind not in ('action', 'foreach'):
            raise UserError(_('Only a failed action may be skipped. Approval and logic cannot be bypassed.'))
        self._log(_('Administrator skipped the failed action.'), 'skipped')
        self._set(state='running', step_id=self.step_id._next().id, attempts=0, delivery_unknown=False)
        self._advance()

    def action_stop(self):
        self._operate()
        if self.state not in ('running', 'waiting', 'failed'):
            raise UserError(_('This run has already finished.'))
        self._log(_('Administrator stopped the run.'), 'stopped')
        self._set(state='stopped', finished_at=fields.Datetime.now())

    @api.model
    def _cron_advance(self):
        # Cron is shipped inactive. Activation of a workflow enables the shared
        # worker only through the explicit activation action.
        runs = self.sudo().search([
            ('is_test', '=', False), ('workflow_id.state', '=', 'active'),
            '|', ('state', '=', 'running'),
            '&', ('state', '=', 'waiting'),
            '|', ('wake_at', '<=', fields.Datetime.now()),
            ('approval_id.state', 'in', ['approved', 'refused']),
        ], limit=100, order='id')
        for run in runs:
            with self.env.cr.savepoint():
                run._advance()
        workflows = self.env['workflow.definition'].sudo().search([
            ('state', '=', 'active'), ('trigger', '=', 'schedule'),
            ('next_run', '<=', fields.Datetime.now())])
        for workflow in workflows:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT id FROM workflow_definition WHERE id = %s FOR UPDATE SKIP LOCKED', [workflow.id])
                if not self.env.cr.fetchone():
                    continue
                workflow.invalidate_recordset()
                user_workflow = workflow.with_user(workflow.user_id).with_context(
                    allowed_company_ids=[workflow.company_id.id]).with_company(workflow.company_id)
                records = user_workflow.env[workflow.model_name].search(
                    workflow._domain() + [('id', '>', workflow.schedule_cursor)], limit=100, order='id')
                for record in records:
                    key = f'{workflow.id}:{workflow.revision}:{workflow.next_run}:{record.id}'
                    if self.sudo().search_count([('run_key', '=', key)]):
                        continue
                    existing = self.search_count([('workflow_id', '=', workflow.id),
                                                  ('record_id', '=', record.id), ('is_test', '=', False),
                                                  ('state', 'in', ['running', 'waiting', 'failed'])])
                    if existing:
                        continue
                    if 'company_id' in record and record.company_id and record.company_id != workflow.company_id:
                        continue
                    run = internal(self.sudo()).create({
                        'workflow_id': workflow.id, 'record_id': record.id, 'name': record.display_name,
                        'revision': workflow.revision, 'run_key': key,
                        'step_id': workflow.step_ids.sorted('sequence')[:1].id,
                    })
                    run._log(_('Queued by the schedule.'), 'queued')
                if len(records) == 100:
                    internal(workflow).write({'schedule_cursor': records[-1].id})
                else:
                    internal(workflow).write({'schedule_cursor': 0, 'next_run': fields.Datetime.now() + timedelta(hours=workflow.interval_hours)})


class RunLog(models.Model):
    _name = 'workflow.run.log'
    _description = 'Workflow Step History'
    _order = 'id'
    run_id = fields.Many2one('workflow.run', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='run_id.company_id', store=True)
    name = fields.Char()
    message = fields.Text()
    state = fields.Char()
    actor_id = fields.Many2one('res.users')
    occurred_at = fields.Datetime(default=fields.Datetime.now)

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self):
            raise AccessError(_('History is written only by workflow execution.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('History cannot be edited.'))

    def unlink(self):
        raise AccessError(_('History cannot be deleted.'))


class WorkflowTest(models.TransientModel):
    _name = 'workflow.test'
    _description = 'Test or Run Workflow'
    workflow_id = fields.Many2one('workflow.definition', required=True)
    model_name = fields.Char(related='workflow_id.model_name')
    record_id = fields.Many2oneReference(model_field='model_name', string='Record', required=True)
    mode = fields.Selection([('preview', 'Preview without changing the record'),
                             ('run', 'Run the active workflow')], default='preview', required=True)

    def action_start(self):
        self.ensure_one()
        workflow = self.workflow_id
        workflow._manager()
        record = self.env[workflow.model_name].browse(self.record_id).exists()
        if not record:
            raise UserError(_('Choose an existing record.'))
        record.check_access('read')
        if self.mode == 'run':
            if workflow.state != 'active':
                raise UserError(_('Activate the reviewed workflow before running it.'))
            workflow._trigger_records(record)
        else:
            issues = workflow._validate()
            run = internal(self.env['workflow.run']).create({
                'workflow_id': workflow.id, 'record_id': record.id, 'name': record.display_name,
                'revision': workflow.revision, 'is_test': True, 'state': 'done',
            })
            record = run._record()
            matched = bool(record.filtered_domain(workflow._domain()))
            run._log(_('Preview only: no actions, messages or webhooks were executed.'))
            if not matched:
                run._log(_('This record does not match the workflow filter.'), 'skipped')
            else:
                step = workflow.step_ids.sorted('sequence')[:1]
                visited = set()
                while step and step.id not in visited:
                    visited.add(step.id)
                    status = 'planned'
                    if step.kind in ('branch', 'condition'):
                        yes = bool(record.filtered_domain(workflow._domain(step.domain)))
                        run._log(_('Condition matches current record: %s', yes), status, step)
                        if not yes:
                            step = step.false_id if step.kind == 'branch' else step.browse()
                            continue
                    else:
                        run._log(_('Would perform this step. Waits are not elapsed and actions are not executed during preview.'), status, step)
                    step = step._next()
            if issues:
                run._log('\n'.join(issues), 'needs_setup')
            else:
                internal(workflow).write({'tested_revision': workflow.revision, 'tested_digest': workflow._fingerprint()})
        return {'type': 'ir.actions.act_window', 'name': _('Run history'),
                'res_model': 'workflow.run', 'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')],
                'domain': [('workflow_id', '=', workflow.id)]}
