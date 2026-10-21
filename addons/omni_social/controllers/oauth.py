"""Platform sign-in returns here; the account manager who started it must finish it."""

from markupsafe import escape
from odoo import http, _
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..models.platform import CALLBACK


def _page(title, message, back):
    body = (
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<title>%s</title></head><body style="font-family:sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem">'
        '<h1 style="font-size:1.25rem">%s</h1><p>%s</p><p><a href="%s">%s</a></p></body></html>'
    ) % (escape(title), escape(title), escape(message), escape(back), escape(_('Back to the account')))
    return request.make_response(body, headers=[('Content-Type', 'text/html; charset=utf-8'),
                                                ('Cache-Control', 'no-store')])


class SocialOAuth(http.Controller):
    @http.route(CALLBACK, type='http', auth='user', methods=['GET'], csrf=False)
    def callback(self, state=None, code=None, error=None, **kw):
        pending = request.env['omni.social.oauth.state']._consume(state)
        if not pending:
            return _page(_('Sign-in expired'), _('Start the sign-in again from the account.'), '/odoo/action-omni_social.accounts')
        connection = request.env['omni.social.connection'].browse(pending['connection_id'][0])
        back = '/odoo/omni.social.connection/%s' % connection.id
        if error or not code or not isinstance(code, str) or len(code) > 4096:
            return _page(_('Sign-in cancelled'), _('The platform did not grant access. Nothing was changed.'), back)

        class Pending:
            verifier = pending['verifier'] or ''
            redirect_uri = pending['redirect_uri']
            account = pending['account'] or ''

        try:
            with request.env.cr.savepoint():
                connection._oauth_finish(Pending, code)
        except (UserError, AccessError) as failure:
            return _page(_('Sign-in did not finish'), str(failure.args[0] if failure.args else failure), back)
        return request.redirect(back, local=True)
