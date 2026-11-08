"""Odoo tools for agents (ADR 0012, phase 3): read-only, called by Hermes through Odoo's MCP endpoint.

Every call carries the run's one-run key (sent in the run's instructions) and comes with the bearer token of the
profile the run was sent to. Data is limited three times: the agent's data scope (models, fields, record filter,
limit), what the agent's assistant user may read, and in a chat also what the person asking may read. Results are
reference data for the model, never instructions.
"""

import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.orm.domains import Domain
from odoo.tools import html2plaintext

from .agent import SCALAR_TYPES

RESULT_MAX = 20000  # characters of JSON returned by one tool call
SEARCH_MAX = 50
MESSAGE_MAX = 2000
FILTER_OPERATORS = {'=', '!=', '<', '<=', '>', '>=', 'ilike', 'not ilike', 'in', 'not in'}
LIVE_STATES = ('submitting', 'running', 'stop_requested')

TOOLS = [
    {'name': 'search_records',
     'description': 'Search records the agent may read. Returns id, display name and the allowed fields.',
     'inputSchema': {'type': 'object', 'required': ['run_key', 'model'], 'properties': {
         'run_key': {'type': 'string', 'description': 'The run key from your instructions.'},
         'model': {'type': 'string', 'description': 'Technical model name, for example res.partner.'},
         'text': {'type': 'string', 'description': 'Words to find in the record name.'},
         'filters': {'type': 'array', 'description': 'Optional conditions [field, operator, value].',
                     'items': {'type': 'array'}},
         'fields': {'type': 'array', 'items': {'type': 'string'}},
         'limit': {'type': 'integer', 'minimum': 1, 'maximum': SEARCH_MAX}}}},
    {'name': 'read_record',
     'description': 'Read one record the agent may read.',
     'inputSchema': {'type': 'object', 'required': ['run_key', 'model', 'id'], 'properties': {
         'run_key': {'type': 'string'}, 'model': {'type': 'string'}, 'id': {'type': 'integer'},
         'fields': {'type': 'array', 'items': {'type': 'string'}}}}},
    {'name': 'record_activities',
     'description': 'Open activities (to-dos) on one record the agent may read.',
     'inputSchema': {'type': 'object', 'required': ['run_key', 'model', 'id'], 'properties': {
         'run_key': {'type': 'string'}, 'model': {'type': 'string'}, 'id': {'type': 'integer'}}}},
    {'name': 'record_messages',
     'description': 'Recent messages and notes on one record the agent may read.',
     'inputSchema': {'type': 'object', 'required': ['run_key', 'model', 'id'], 'properties': {
         'run_key': {'type': 'string'}, 'model': {'type': 'string'}, 'id': {'type': 'integer'},
         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}}}},
    # Prepare-only (phase 4): each creates an approval request; nothing changes until a person approves it.
    {'name': 'propose_note',
     'description': 'Propose an internal note on a record. A person approves it before it is posted.',
     'inputSchema': {'type': 'object', 'required': ['run_key', 'model', 'id', 'text'], 'properties': {
         'run_key': {'type': 'string'}, 'model': {'type': 'string'}, 'id': {'type': 'integer'},
         'text': {'type': 'string', 'maxLength': 4000}}}},
    {'name': 'propose_activity',
     'description': 'Propose a to-do on a record for the person who asked. A person approves it before it is created.',
     'inputSchema': {'type': 'object', 'required': ['run_key', 'model', 'id', 'summary', 'due_date'], 'properties': {
         'run_key': {'type': 'string'}, 'model': {'type': 'string'}, 'id': {'type': 'integer'},
         'summary': {'type': 'string', 'maxLength': 200}, 'note': {'type': 'string', 'maxLength': 4000},
         'due_date': {'type': 'string', 'description': 'YYYY-MM-DD'}}}},
    {'name': 'propose_change',
     'description': 'Propose new values for fields of a record. A person approves it before anything changes.',
     'inputSchema': {'type': 'object', 'required': ['run_key', 'model', 'id', 'values'], 'properties': {
         'run_key': {'type': 'string'}, 'model': {'type': 'string'}, 'id': {'type': 'integer'},
         'values': {'type': 'object', 'description': 'Field name to new value, for fields the agent may read.'},
         'reason': {'type': 'string', 'maxLength': 1000}}}},
]


def key_hash(value):
    return hashlib.sha256((value or '').encode()).hexdigest()


class ToolCallError(Exception):
    """A tool call the agent made wrongly; the message goes back to the model."""


class AgentTools(models.AbstractModel):
    _name = 'ai.agent.tools'
    _description = 'Agent tools'

    # -- who is calling --------------------------------------------------------------------------------------
    @api.model
    def _profile_for_token(self, token):
        """The profile whose MCP bearer token this is (privileged lookup), or an empty recordset."""
        if not token or len(token) > 200:
            return self.env['ai.agent.profile']
        return self.env['ai.agent.profile'].sudo().search(
            [('mcp_token_hash', '=', key_hash(token)), ('active', '=', True)], limit=1)

    @api.model
    def _run_for(self, profile, run_key):
        """The live run of this profile holding this one-run key."""
        if not isinstance(run_key, str) or not run_key or len(run_key) > 200:
            raise ToolCallError(_('Pass the run_key from your instructions.'))
        run = self.env['ai.agent.run'].sudo().search([('tool_key_hash', '=', key_hash(run_key)),
                                                       ('profile_id', '=', profile.id),
                                                       ('state', 'in', LIVE_STATES)], limit=1)
        if not run:
            raise ToolCallError(_('This run_key is not valid for a run in progress.'))
        return run

    @api.model
    def _acting_users(self, run):
        """The assistant user (if the agent's department or company has one), then the person who asked."""
        assistant = run.agent_id._assistant_user()
        users = []
        if assistant and assistant.active:
            users.append(assistant)
        if run.user_id and run.user_id not in users:
            users.append(run.user_id)
        if not users:
            raise ToolCallError(_('Nobody this agent can act as.'))
        return users

    # -- scope and permissions -------------------------------------------------------------------------------
    @api.model
    def _scope(self, run, model_name):
        access = run.agent_id.sudo().access_ids.filtered(lambda a: a.model_name == model_name)[:1]
        if not access:
            allowed = ', '.join(sorted(set(run.agent_id.sudo().access_ids.mapped('model_name')))) or _('none')
            raise ToolCallError(_('This agent may not read %(model)s. It may read: %(allowed)s.',
                                  model=model_name, allowed=allowed))
        return access

    @api.model
    def _env_for(self, user, run):
        company = run.agent_id.sudo().company_id
        return self.env(user=user.id, su=False, context={'allowed_company_ids': [company.id],
                                                          'active_test': True})

    @api.model
    def _allowed_fields(self, run, access, users, requested):
        """Fields in the scope that every acting user may read."""
        scope = set(access._fields_allowed(self.env[access.model_name]))
        wanted = scope if not requested else set(requested) & scope
        names = []
        for name in sorted(wanted):
            field = self.env[access.model_name]._fields.get(name)
            if field and field.type in SCALAR_TYPES and all(
                    self._env_for(user, run)[access.model_name]._has_field_access(field, 'read') for user in users):
                names.append(name)
        return names

    @api.model
    def _base_domain(self, run, access):
        model = self.env[access.model_name]
        domain = Domain(json.loads(access.domain_json or '[]'))
        if 'company_id' in model._fields:
            company = run.agent_id.sudo().company_id
            domain &= Domain.OR([Domain('company_id', '=', False), Domain('company_id', '=', company.id)])
        return domain

    @api.model
    def _permitted(self, records, users, run):
        """Records every acting user may read (record rules and access rights of each)."""
        for user in users:
            records = records.with_env(self._env_for(user, run))._filtered_access('read')
        return records

    @api.model
    def _filter_domain(self, filters, field_names):
        domain = Domain.TRUE
        if not filters:
            return domain
        if not isinstance(filters, list) or len(filters) > 10:
            raise ToolCallError(_('Pass at most 10 filters as [field, operator, value].'))
        for item in filters:
            if not (isinstance(item, list) and len(item) == 3 and item[0] in field_names
                    and item[1] in FILTER_OPERATORS and isinstance(item[2], (str, int, float, bool, list))):
                raise ToolCallError(_('Filters use allowed fields (%s) and simple operators.', ', '.join(field_names)))
            domain &= Domain(item[0], item[1], item[2])
        return domain

    # -- tools -----------------------------------------------------------------------------------------------
    @api.model
    def _call(self, profile, name, arguments):
        """Run one tool call for a profile's MCP connection; returns (result, is_error)."""
        arguments = arguments if isinstance(arguments, dict) else {}
        run = None
        try:
            run = self._run_for(profile, arguments.get('run_key'))
            handler = {'search_records': self._tool_search, 'read_record': self._tool_read,
                       'record_activities': self._tool_activities, 'record_messages': self._tool_messages,
                       'propose_note': self._tool_propose_note, 'propose_activity': self._tool_propose_activity,
                       'propose_change': self._tool_propose_change}.get(name)
            if not handler:
                raise ToolCallError(_('Unknown tool %s.', name))
            result = handler(run, arguments)
            text = json.dumps(result, default=str)
            if len(text) > RESULT_MAX:
                text = text[:RESULT_MAX] + '…'
            run._event('tool', _('%(tool)s on %(model)s: %(summary)s', tool=name, model=arguments.get('model'),
                                 summary=result.get('summary', '') if isinstance(result, dict) else ''))
            return text, False
        except (ToolCallError, AccessError, UserError, ValueError) as error:
            message = str(error.args[0] if error.args else error)
            if run:
                run._event('tool', _('%(tool)s refused: %(reason)s', tool=name, reason=message))
            return message, True

    def _records(self, run, arguments, record_id=None):
        model_name = arguments.get('model')
        if not isinstance(model_name, str):
            raise ToolCallError(_('Pass the model name.'))
        access = self._scope(run, model_name)
        users = self._acting_users(run)
        field_names = self._allowed_fields(run, access, users, arguments.get("fields"))
        domain = self._base_domain(run, access)
        if record_id is not None:
            if not isinstance(record_id, int):
                raise ToolCallError(_('Pass the record id as a number.'))
            domain &= Domain('id', '=', record_id)
        return access, users, field_names, domain

    def _tool_search(self, run, arguments):
        access, users, field_names, domain = self._records(run, arguments)
        domain &= self._filter_domain(arguments.get('filters'), field_names)
        text = arguments.get('text')
        if text:
            domain &= Domain('display_name', 'ilike', str(text)[:100])
        limit = min(int(arguments.get('limit') or access.limit), access.limit, SEARCH_MAX)
        model = self._env_for(users[0], run)[access.model_name]
        records = self._permitted(model.search(domain, limit=limit, order=access._search_order(model)), users, run)
        rows = records.read(field_names, load=None)
        for row, record in zip(rows, records):
            row['display_name'] = record.display_name
        return {'model': access.model_name, 'records': rows, 'summary': _('%s records', len(rows))}

    def _single(self, run, arguments):
        access, users, field_names, domain = self._records(run, arguments, arguments.get('id'))
        model = self._env_for(users[0], run)[access.model_name]
        record = self._permitted(model.search(domain, limit=1), users, run)
        if not record:
            raise ToolCallError(_('No record %s that this agent may read.', arguments.get('id')))
        return access, users, field_names, record

    def _tool_read(self, run, arguments):
        access, _users, field_names, record = self._single(run, arguments)
        row = record.read(field_names, load=None)[0]
        row['display_name'] = record.display_name
        return {'model': access.model_name, 'record': row, 'summary': _('1 record')}

    def _tool_activities(self, run, arguments):
        access, users, _fields, record = self._single(run, arguments)
        activities = self._env_for(users[0], run)['mail.activity'].search(
            [('res_model', '=', access.model_name), ('res_id', '=', record.id)], limit=20, order='date_deadline')
        activities = self._permitted(activities, users, run)
        rows = [{'type': a.activity_type_id.name, 'summary': a.summary or '', 'due': str(a.date_deadline),
                 'assigned_to': a.user_id.name, 'state': a.state,
                 'note': html2plaintext(a.note or '')[:MESSAGE_MAX]} for a in activities]
        return {'record': record.display_name, 'activities': rows, 'summary': _('%s activities', len(rows))}

    def _tool_messages(self, run, arguments):
        access, users, _fields, record = self._single(run, arguments)
        limit = min(int(arguments.get('limit') or 10), 20)
        messages = self._env_for(users[0], run)['mail.message'].search(
            [('model', '=', access.model_name), ('res_id', '=', record.id),
             ('message_type', 'in', ('comment', 'email'))], limit=limit, order='date desc, id desc')
        messages = self._permitted(messages, users, run)
        rows = [{'date': str(m.date), 'author': m.author_id.name or m.email_from or '',
                 'text': html2plaintext(m.body or '')[:MESSAGE_MAX]} for m in messages]
        return {'record': record.display_name, 'messages': rows, 'summary': _('%s messages', len(rows))}

    # -- prepare-only tools ----------------------------------------------------------------------------------
    def _proposable(self, run, arguments):
        access, users, field_names, record = self._single(run, arguments)
        if not access.can_propose:
            raise ToolCallError(_('This agent may only read %s; it may not propose changes.', access.model_name))
        if run.user_id.ai_assistant:
            # A workflow asked (no person): the workflow's own steps make the changes.
            raise ToolCallError(_('Nobody asked in person, so there is nobody to approve a proposal. Answer only.'))
        return access, users, field_names, record

    def _sent(self, proposal, request):
        approvers = ', '.join(request.sudo().approver_ids.user_id.mapped('name'))
        return {'proposal': proposal.id, 'approval_request': request.id, 'state': 'waiting for approval',
                'approvers': approvers,
                'summary': _('proposal %(id)s sent to %(approvers)s', id=proposal.id, approvers=approvers)}

    def _tool_propose_note(self, run, arguments):
        _access, _users, _fields, record = self._proposable(run, arguments)
        text = str(arguments.get('text') or '').strip()[:4000]
        if not text:
            raise ToolCallError(_('Pass the note text.'))
        proposal, request = self.env['ai.agent.proposal']._propose(
            run, 'note', record, _('Note on %s', record.display_name), text=text)
        return self._sent(proposal, request)

    def _tool_propose_activity(self, run, arguments):
        _access, _users, _fields, record = self._proposable(run, arguments)
        summary = str(arguments.get('summary') or '').strip()[:200]
        try:
            due = fields.Date.to_date(arguments.get('due_date'))
        except (TypeError, ValueError):
            due = None
        if not summary or not due:
            raise ToolCallError(_('Pass a summary and a due_date as YYYY-MM-DD.'))
        proposal, request = self.env['ai.agent.proposal']._propose(
            run, 'activity', record, _('To-do on %(record)s: %(summary)s', record=record.display_name, summary=summary),
            text=str(arguments.get('note') or '')[:4000], values={'summary': summary, 'due': str(due)})
        return self._sent(proposal, request)

    def _tool_propose_change(self, run, arguments):
        access, users, field_names, record = self._proposable(run, arguments)
        values = arguments.get('values')
        if not isinstance(values, dict) or not values or len(values) > 20:
            raise ToolCallError(_('Pass values as {field: new value}.'))
        writable = set(self._allowed_fields(run, access, users, list(values)))
        for name, value in values.items():
            if name not in writable or name in ('id', 'company_id'):
                raise ToolCallError(_('%(field)s is not a field this agent may propose. It may use: %(fields)s.',
                                      field=name, fields=', '.join(sorted(set(field_names) - {'id'}))))
            if not isinstance(value, (str, int, float, bool)) and value is not None:
                raise ToolCallError(_('%s takes a simple value (text, number, true/false or a date).', name))
        reason = str(arguments.get('reason') or '')[:1000]
        proposal, request = self.env['ai.agent.proposal']._propose(
            run, 'change', record, _('Change %(fields)s on %(record)s', fields=', '.join(values), record=record.display_name),
            text=reason, values=values)
        return self._sent(proposal, request)

