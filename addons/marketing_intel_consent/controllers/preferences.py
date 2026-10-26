"""Public preference page: a person opens their private link and chooses channels and topics."""

from odoo import _, http
from odoo.http import request

from ..models.consent import CHANNELS


class Preferences(http.Controller):

    def _subject(self, token):
        if not token or len(token) < 20:
            return None
        return request.env['mi.consent.subject'].sudo().search([('token', '=', token), ('erased', '=', False)], limit=1)

    @http.route('/marketing/preferences/<string:token>', type='http', auth='public', methods=['GET', 'POST'],
                website=False, sitemap=False)
    def preferences(self, token, **post):
        subject = self._subject(token)
        if not subject:
            return request.render('marketing_intel_consent.preferences_missing', status=404)
        saved = False
        if request.httprequest.method == 'POST':
            agent = (request.httprequest.user_agent.string or '')[:120]
            evidence = _('Chosen on the preference page from %(ip)s (%(agent)s).',
                         ip=request.httprequest.remote_addr, agent=agent)
            channels = [code for code, _label in CHANNELS if post.get('channel_%s' % code)]
            topics = [int(key.split('_', 1)[1]) for key in post if key.startswith('topic_') and key[6:].isdigit()]
            subject._apply_preferences(channels, topics, evidence, unsubscribe_all=bool(post.get('unsubscribe_all')))
            saved = True
        topics = request.env['mi.consent.topic'].sudo().search([('company_id', 'in', [False, subject.company_id.id])])
        return request.render('marketing_intel_consent.preferences_page', {
            'subject': subject, 'channels': CHANNELS, 'topics': topics, 'saved': saved,
            'company': subject.company_id, 'token': token,
        })
