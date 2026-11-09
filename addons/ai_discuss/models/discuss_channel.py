"""Assistant chats in Discuss (ADR 0013, phase 2; approved mocks 2026-11-08, boards 10 and 12).

An assistant chat is a normal Discuss direct chat between a person and an agent's chat partner. A message the
person sends there is one question to the agent: it is queued as an ``ai.agent.run`` for that person (their rights
and the assistant's, ADR 0012), and the answer is posted in the chat by the agent's partner when the run finishes.
Nothing is changed without approval: proposals are listed with a link to their approval request.
"""

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext, plaintext2html

from odoo.addons.ai_agent.models.common import internal
from odoo.addons.mail.tools.discuss import Store


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    ai_agent_id = fields.Many2one('ai.agent', string='Assistant', readonly=True, index='btree_not_null',
                                  ondelete='set null', help='The AI agent this direct chat is with.')
    ai_conversation_id = fields.Many2one('ai.agent.conversation', readonly=True, ondelete='set null',
                                         help='The agent conversation the questions of this chat continue.')

    # ------------------------------------------------------------------
    # Chats with assistants
    # ------------------------------------------------------------------

    @api.model
    def _ai_ensure_assistant_chats(self):
        """Every assistant the user may chat with, answering or paused, has a chat in Discuss, made once (like
        OdooBot's); a chat the user later hides stays hidden."""
        partner = self.env.user.partner_id
        agents = self.env['ai.agent'].search([('state', 'in', ('active', 'paused')), ('can_chat', '=', True)])
        if not agents:
            return self.browse()
        # sudo: discuss.channel - find the user's chats with these agents, pinned or not.
        known = self.sudo().search([('ai_agent_id', 'in', agents.ids),
                                    ('channel_member_ids.partner_id', '=', partner.id)]).ai_agent_id
        chats = self.browse()
        for agent in agents - known:
            agent_partner = agent.sudo().partner_id
            if not agent_partner:
                continue
            chat = self._get_or_create_chat([agent_partner.id])
            # sudo: discuss.channel - the agent of a chat is set here only, never by the person.
            chat.sudo().ai_agent_id = agent
            chats |= chat
        return chats

    def _ai_agent_partner(self):
        return self.sudo().ai_agent_id.partner_id

    def _ai_typing(self, is_typing):
        """Show or clear "<agent> is typing…" while the agent prepares its answer."""
        for channel in self:
            member = channel.sudo().channel_member_ids.filtered(
                lambda m, partner=channel._ai_agent_partner(): m.partner_id == partner)
            member._notify_typing(is_typing)

    def _ai_reply(self, body):
        """Post in the chat as the agent's partner."""
        self.ensure_one()
        partner = self._ai_agent_partner()
        # sudo: discuss.channel - the agent's partner is a member of the chat but not a user.
        self.sudo().message_post(author_id=partner.id, body=body, message_type='comment',
                                 subtype_xmlid='mail.mt_comment')
        self._ai_typing(False)

    def _message_post_after_hook(self, message):
        result = super()._message_post_after_hook(message)
        if (self.channel_type == 'chat' and self.sudo().ai_agent_id and message.message_type == 'comment'
                and message.author_id and message.author_id == self.env.user.partner_id
                and message.author_id != self._ai_agent_partner() and not self.env.user.share):
            self._ai_ask(message)
        return result

    def _ai_ask(self, message):
        """One message is one question to the agent, asked as the person who wrote it."""
        self.ensure_one()
        prompt = html2plaintext(message.body or '').strip()
        if not prompt:
            return
        agent = self.env['ai.agent'].browse(self.sudo().ai_agent_id.id)
        conversation = self.sudo().ai_conversation_id.with_env(self.env)
        try:
            run = self.env['ai.agent.run']._ask(agent, prompt, caller='chat', conversation=conversation or None,
                                                origin=self)
        except (AccessError, UserError) as error:
            self._ai_reply(Markup('<p>%s</p>') % str(error))
            return
        if not conversation:
            # sudo: discuss.channel - remember the conversation so follow-ups continue it.
            self.sudo().ai_conversation_id = run.sudo().conversation_id
        self._ai_typing(True)

    @api.model
    def _ai_chat_for(self, agent):
        """The current user's direct chat with this agent, made if needed."""
        agent.check_access('read')
        agent._usable()
        partner = agent.sudo().partner_id
        if not partner:
            raise UserError(_('%s has no chat yet.', agent.sudo().name))
        # sudo: discuss.channel - find the user's chat with this agent, pinned or not.
        chat = self.sudo().search([('ai_agent_id', '=', agent.id), ('channel_type', '=', 'chat'),
                                   ('channel_member_ids.partner_id', '=', self.env.user.partner_id.id)], limit=1)
        if not chat:
            chat = self._get_or_create_chat([partner.id])
            # sudo: discuss.channel - the agent of a chat is set here only, never by the person.
            chat.sudo().ai_agent_id = agent
        return self.browse(chat.id)

    def _ai_post_question(self, question):
        """Post the person's question in this chat; it is asked like any message they write. Returns the run."""
        self.ensure_one()
        Run = self.env['ai.agent.run'].sudo()
        before = Run.search([('user_id', '=', self.env.uid)], order='id desc', limit=1).id or 0
        self.message_post(body=plaintext2html(question), message_type='comment', subtype_xmlid='mail.mt_comment')
        run = Run.search([('user_id', '=', self.env.uid), ('id', '>', before), ('origin_model', '=', self._name),
                          ('origin_res_id', '=', self.id)], order='id desc', limit=1)
        if not run:
            raise UserError(_('%s could not take the question; see the chat.', self.sudo().ai_agent_id.name))
        return run

    def _ai_chosen_note(self, agent, why, router):
        """'Chosen for you: <agent>, for <why>. Change' above the routed question (approved board 20)."""
        self.ensure_one()
        text = _('Chosen for you: %(agent)s, for %(why)s.', agent=agent.sudo().name, why=why) if why \
            else _('Chosen for you: %s.', agent.sudo().name)
        body = Markup('<p>%s <a href="/odoo/ai.agent.run/%s/action-ai_discuss.action_route_change">%s</a></p>') % (
            text, router.id, _('Change'))
        # sudo: discuss.channel - a system line of the chat, not a message of the person.
        self.sudo().message_post(body=body, message_type='notification', subtype_xmlid='mail.mt_note')

    def _ai_agent_asking(self, run, child):
        """The agent asked another agent (ADR 0015): '<agent> is asking <other> about …' until the answer comes."""
        self.ensure_one()
        run, child = run.sudo(), child.sudo()
        body = Markup('<p>↳ %s <a href="/odoo/ai.agent.run/%s">%s</a></p>') % (
            _('%(agent)s is asking %(other)s about %(question)s…', agent=run.agent_id.name,
              other=child.agent_id.name, question=(child.prompt or '')[:120]), run.id, _('Stop'))
        partner = self._ai_agent_partner()
        # sudo: discuss.channel - the agent's partner is a member of the chat but not a user.
        message = self.sudo().message_post(author_id=partner.id, body=body, message_type='notification',
                                           subtype_xmlid='mail.mt_note')
        internal(run).write({'ai_asking_message_ids': (run.ai_asking_message_ids or []) + [message.id]})
        self._ai_typing(True)

    def _ai_agent_finished(self, run):
        """The run asked from this chat finished: post its answer, or say why there is none."""
        self.ensure_one()
        run = run.sudo()
        asked = run.followup_of_id
        if asked.ai_asking_message_ids:
            # The status lines are replaced by the answer.
            self.env['mail.message'].sudo().browse(asked.ai_asking_message_ids).exists().unlink()
        if run.state == 'completed':
            body = plaintext2html(run.answer or '')
            if asked.child_run_ids:
                lines = []
                for child in asked.child_run_ids:
                    lines.append(Markup('%s <a href="/odoo/ai.agent.run/%s">%s</a>') % (
                        self.env._('Asked %(agent)s: %(question)s', agent=child.agent_id.name, question=child.name),
                        child.id, self.env._('View')))
                body += Markup('<p><small>%s</small></p>') % Markup(' · ').join(lines)
            for proposal in self.env['ai.agent.proposal'].sudo().search([('run_id', '=', run.id)]):
                body += Markup('<p><b>%s</b> · %s · <a href="/odoo/approval.center.request/%s">%s</a></p>') % (
                    _('Proposed: %s', proposal.name), _('Waiting for approval'), proposal.request_id.id,
                    _('Open request'))
        else:
            body = Markup('<p>%s</p>') % (run.error_message or _('No answer this time. Ask again.'))
        self._ai_reply(body)

    # ------------------------------------------------------------------
    # Web client
    # ------------------------------------------------------------------

    def _store_channel_fields(self, res: Store.FieldList):
        super()._store_channel_fields(res)
        is_assistant_chat = lambda channel: bool(channel.sudo().ai_agent_id)  # noqa: E731
        # sudo: ai.agent - what the chat list shows of the assistant: its owner, description and whether it answers.
        res.attr('ai_agent_id', lambda c: c.sudo().ai_agent_id.id, predicate=is_assistant_chat)
        res.attr('ai_agent_department', lambda c: c.sudo().ai_agent_id.department_id.name or c.env._('Company'),
                 predicate=is_assistant_chat)
        res.attr('ai_agent_description', lambda c: c.sudo().ai_agent_id.description or '',
                 predicate=is_assistant_chat)
        res.attr('ai_agent_paused', lambda c: c.sudo().ai_agent_id.state != 'active', predicate=is_assistant_chat)
