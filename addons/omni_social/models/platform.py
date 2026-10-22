"""Shared groundwork for every social connector.

- OAuth sign-in: the account manager enters the developer app's ID and secret
  once, then clicks Connect and signs in on the platform. Tokens and the app
  secret live only in the encrypted vault; refresh happens when a token is
  about to expire.
- Usage meter: daily platform caps and, for paid platforms, a monthly budget
  are enforced before the first call of each approved publication.
- Catalogue link: Omnichannel's channel catalogue learns which platforms are
  connected here, so its channel picker can send people to Social.
"""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from .social import internal, trusted, Connection as BaseConnection
from ..providers import vault
from ..providers.capabilities import OPERATION_LABELS
from ..providers.http import ProviderError, call_form
from ..providers.registry import capabilities, installed

CALLBACK = '/omni/social/oauth/callback'
DEFAULT_BUDGET = 20.0  # USD per month for paid platforms (plan decision 3, default)
STATE_MINUTES = 10
REFRESH_MARGIN = timedelta(minutes=5)


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _month_start(now):
    return datetime(now.year, now.month, 1)


class Connection(models.Model):
    _inherit = 'omni.social.connection'

    capabilities = fields.Json(compute='_compute_capabilities')
    rules_summary = fields.Char(compute='_compute_capabilities', string='Platform rules')
    oauth_available = fields.Boolean(compute='_compute_capabilities')
    paid_platform = fields.Boolean(compute='_compute_capabilities')
    oauth_client_id = fields.Char(
        readonly=True, copy=False, string='App ID', groups='omni_channel.group_omni_manager'
    )
    oauth_app_reference = fields.Char(readonly=True, copy=False, groups='omni_channel.group_omni_manager')
    oauth_ready = fields.Boolean(compute='_compute_oauth_ready', string='Sign-in ready')
    oauth_redirect_url = fields.Char(compute='_compute_oauth_ready', string='Redirect URL')
    monthly_budget = fields.Float(
        string='Monthly budget (USD)',
        default=0.0,
        help='Paid platforms only. Publishing stops for the month once this amount would be exceeded.',
    )
    usage_ids = fields.One2many('omni.social.usage', 'connection_id', readonly=True, string='Usage records')
    month_cost = fields.Float(compute='_compute_usage', string='Spent this month (USD)')
    usage_summary = fields.Char(compute='_compute_usage', string='Usage')
    _protected = BaseConnection._protected | {'oauth_client_id', 'oauth_app_reference'}

    @api.depends('provider')
    def _compute_capabilities(self):
        for row in self:
            caps = capabilities(row.provider)
            row.capabilities = caps.as_dict() if caps else {}
            row.rules_summary = caps.summary() if caps else ''
            row.oauth_available = bool(caps and caps.oauth)
            row.paid_platform = bool(caps and caps.paid())

    @api.depends('provider', 'public_url')
    @api.depends_context('uid')
    def _compute_oauth_ready(self):
        manager = self.env.user.has_group('omni_channel.group_omni_manager')
        for row in self:
            caps = capabilities(row.provider)
            reference = row.sudo().oauth_app_reference if manager else False
            row.oauth_ready = bool(caps and caps.oauth and reference and row.public_url)
            row.oauth_redirect_url = (row.public_url.rstrip('/') + CALLBACK) if row.public_url else ''

    @api.depends('usage_ids', 'provider', 'monthly_budget')
    def _compute_usage(self):
        now = fields.Datetime.now()
        for row in self:
            caps = capabilities(row.provider)
            if not caps or not row.id:
                row.month_cost = 0.0
                row.usage_summary = ''
                continue
            usage = row.sudo().usage_ids
            month = usage.filtered(lambda u: u.create_date >= _month_start(now))
            row.month_cost = sum(month.mapped('cost'))
            parts = []
            for operation, limit in caps.daily_limits.items():
                used = len(usage.filtered(lambda u: u.operation == operation and u.create_date >= now - timedelta(hours=24)))
                parts.append(
                    _('%(used)s of %(limit)s %(what)s in the last 24 h',
                      used=used, limit=format(limit, ','), what=OPERATION_LABELS.get(operation, operation))
                )
            if caps.paid():
                parts.append(_('$%(spent).2f of $%(budget).2f this month', spent=row.month_cost, budget=row.monthly_budget))
            row.usage_summary = ' · '.join(parts)

    @api.depends('connected', 'profile_name', 'provider', 'account_kind')
    @api.depends_context('uid')
    def _compute_ui(self):
        super()._compute_ui()
        manager = self.env.user.has_group('omni_channel.group_omni_manager')
        for row in self:
            caps = capabilities(row.provider)
            row.credentials_ui = {
                **row.credentials_ui,
                'installed': bool(caps) and row.provider in installed(self.env),
                'label': caps.label if caps else '',
                'oauth': bool(caps and caps.oauth),
                'oauth_app': bool(manager and row.sudo().oauth_app_reference),
                'app_id': (row.sudo().oauth_client_id or '') if manager else '',
                'public_url': bool(row.public_url),
                'token_hint': caps.token_hint if caps else '',
                'developer_url': caps.developer_url if caps else '',
                'account_label': caps.account_label if caps and caps.asks_account(row.account_kind) else '',
                'account_required': bool(caps and caps.account_required_for and row.account_kind in caps.account_required_for),
            }

    # ---- OAuth sign-in -------------------------------------------------

    def _app(self):
        self.ensure_one()
        reference = self.sudo().oauth_app_reference
        if not reference:
            raise UserError(_('Enter the developer app ID and secret first.'))
        return vault.load(
            reference,
            database=self.env.cr.dbname,
            company_id=self.company_id.id,
            purpose_id=self.purpose_id.id,
            provider=self.provider,
            account_key='app',
        )

    def action_oauth_app(self, client_id, client_secret):
        """Keep the developer app's ID and secret for sign-in (managers only)."""
        self.ensure_one()
        self._require_manager()
        self._lock()
        caps = self._caps()
        if not caps or not caps.oauth:
            raise UserError(_('This platform does not offer sign-in here. Paste an access token instead.'))
        for value in (client_id, client_secret):
            if not isinstance(value, str) or not 4 <= len(value.strip()) <= 512 or '\n' in value:
                raise UserError(_('Enter the app ID and secret from the developer portal.'))
        ref = vault.store(
            {
                'database': self.env.cr.dbname,
                'company_id': self.company_id.id,
                'purpose_id': self.purpose_id.id,
                'provider': self.provider,
                'account_key': 'app',
                'client_id': client_id.strip(),
                'client_secret': client_secret.strip(),
            }
        )
        self.env.cr.postrollback.add(lambda: vault.remove(ref, self.env.cr.dbname))
        old = self.sudo().oauth_app_reference
        if old:
            self.env.cr.postcommit.add(lambda: vault.remove(old, self.env.cr.dbname))
        internal(self.sudo()).write({'oauth_app_reference': ref, 'oauth_client_id': client_id.strip()})
        self._audit('social.oauth_app', _('Developer app saved for sign-in.'))
        return True

    def action_oauth_start(self, account=''):
        """Return the platform's sign-in page for this account."""
        self.ensure_one()
        self._require_manager()
        caps = self._caps()
        if not caps or not caps.oauth:
            raise UserError(_('This platform does not offer sign-in here.'))
        if not self.public_url:
            raise UserError(_('Set the public HTTPS address first; the platform returns here after sign-in.'))
        app = self._app()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48) if caps.oauth.pkce else ''
        redirect = self.public_url.rstrip('/') + CALLBACK
        adapter = self._provider()
        scopes = adapter.oauth_scopes(self.account_kind) if hasattr(adapter, 'oauth_scopes') else caps.oauth.scopes
        params = {
            'response_type': 'code',
            caps.oauth.client_id_param: app['client_id'],
            'redirect_uri': redirect,
            'state': state,
            'scope': caps.oauth.scope_separator.join(scopes),
            **dict(caps.oauth.extra),
        }
        if verifier:
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            params.update({'code_challenge': challenge, 'code_challenge_method': 'S256'})
        internal(self.env['omni.social.oauth.state']).sudo().create(
            {
                'connection_id': self.id,
                'user_id': self.env.uid,
                'state_hash': _hash(state),
                'verifier': verifier,
                'redirect_uri': redirect,
                'account': (account or '').strip()[:100],
                'expires_at': fields.Datetime.now() + timedelta(minutes=STATE_MINUTES),
            }
        )
        return {
            'type': 'ir.actions.act_url',
            'url': caps.oauth.authorize_url + '?' + urlencode(params),
            'target': 'self',
        }

    def _oauth_finish(self, pending, code):
        """Exchange the returned code for a token, verify it and store it."""
        self.ensure_one()
        self._require_manager()
        self._lock()
        caps = self._caps()
        app = self._app()
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': pending.redirect_uri,
        }
        if pending.verifier:
            data['code_verifier'] = pending.verifier
        basic = None
        if caps.oauth.client_auth == 'basic':
            basic = (app['client_id'], app['client_secret'])
            data[caps.oauth.client_id_param] = app['client_id']
        else:
            data.update({caps.oauth.client_id_param: app['client_id'], 'client_secret': app['client_secret']})
        try:
            response = call_form(caps.oauth.token_url, data, basic=basic)
            token, details = self._provider().oauth_token(response, app, pending.account)
        except (ProviderError, ValueError, KeyError):
            raise UserError(
                _('Sign-in did not finish. Check the app ID, secret, redirect URL and the permissions you granted.')
            ) from None
        extra = dict(details or {})
        if response.get('refresh_token'):
            extra['refresh_token'] = response['refresh_token']
        if isinstance(response.get('expires_in'), (int, float)) and not extra.get('expires_at'):
            extra['expires_at'] = (fields.Datetime.now() + timedelta(seconds=int(response['expires_in']))).isoformat()
        return self._store_verified(token, pending.account, extra)

    def _bundle(self):
        bundle = super()._bundle()
        expires = bundle.get('expires_at')
        own_refresh = hasattr(type(self._provider()), 'oauth_refresh') if expires else False
        if not expires or not (bundle.get('refresh_token') or own_refresh):
            return bundle
        try:
            due = datetime.fromisoformat(expires) - REFRESH_MARGIN <= fields.Datetime.now()
        except (TypeError, ValueError):
            due = True
        return self._refresh(bundle) if due else bundle

    def _refresh(self, bundle):
        """Swap an expiring token for a fresh one; the review revision is kept."""
        caps = self._caps()
        if not caps or not caps.oauth:
            return bundle
        adapter = self._provider()
        if hasattr(adapter, 'oauth_refresh'):
            # Platforms with their own renewal call (e.g. Threads long-lived tokens).
            try:
                response = adapter.oauth_refresh(bundle)
            except (ProviderError, ValueError):
                raise UserError(_('The platform sign-in expired. Connect the account again.')) from None
            return self._store_refreshed(bundle, response)
        app = self._app()
        data = {'grant_type': 'refresh_token', 'refresh_token': bundle['refresh_token']}
        basic = None
        if caps.oauth.client_auth == 'basic':
            basic = (app['client_id'], app['client_secret'])
        else:
            data.update({caps.oauth.client_id_param: app['client_id'], 'client_secret': app['client_secret']})
        try:
            response = call_form(caps.oauth.token_url, data, basic=basic)
        except (ProviderError, ValueError):
            raise UserError(_('The platform sign-in expired. Connect the account again.')) from None
        return self._store_refreshed(bundle, response)

    def _store_refreshed(self, bundle, response):
        token = response.get('access_token')
        if not isinstance(token, str) or not token:
            raise UserError(_('The platform sign-in expired. Connect the account again.'))
        fresh = {**bundle, 'token': token}
        if response.get('refresh_token'):
            fresh['refresh_token'] = response['refresh_token']
        if isinstance(response.get('expires_in'), (int, float)):
            fresh['expires_at'] = (fields.Datetime.now() + timedelta(seconds=int(response['expires_in']))).isoformat()
        ref = vault.store(fresh)
        old = self.sudo().credential_reference
        self.env.cr.postrollback.add(lambda: vault.remove(ref, self.env.cr.dbname))
        self.env.cr.postcommit.add(lambda: vault.remove(old, self.env.cr.dbname))
        internal(self.sudo()).write({'credential_reference': ref})
        return fresh

    @api.model_create_multi
    def create(self, values):
        for vals in values:
            caps = capabilities(vals.get('provider') or self.env.context.get('default_provider'))
            if caps and caps.paid() and 'monthly_budget' not in vals:
                vals['monthly_budget'] = DEFAULT_BUDGET
        return super().create(values)

    def action_sync(self):
        """On platforms that charge for reads, check and record the cost of a sync."""
        self.ensure_one()
        caps = self._caps()
        price = 0.0
        if caps and caps.costs.get('read'):
            adapter = self._provider()
            price = float(adapter.read_cost() if hasattr(adapter, 'read_cost') else caps.costs['read'])
            now = fields.Datetime.now()
            spent = sum(self.env['omni.social.usage'].sudo().search(
                [('connection_id', '=', self.id), ('create_date', '>=', _month_start(now))]).mapped('cost'))
            if spent + price > self.monthly_budget + 1e-9:
                raise UserError(
                    _('%(platform)s charges for reading. A sync can cost up to $%(price).2f and $%(spent).2f of the '
                      '$%(budget).2f monthly budget is used.', platform=caps.label, price=price, spent=spent,
                      budget=self.monthly_budget)
                )
        result = super().action_sync()
        if price:
            internal(self.env['omni.social.usage']).sudo().create(
                {'connection_id': self.id, 'operation': 'read', 'cost': price})
        return result

    # ---- Usage meter ---------------------------------------------------

    def _price(self, operation, doc):
        caps = self._caps()
        if not caps or not caps.paid():
            return 0.0
        adapter = self._provider()
        if hasattr(adapter, 'cost'):
            return float(adapter.cost(operation, doc))
        return float(caps.costs.get(operation, 0.0))

    def _check_quota(self, operation, doc):
        self.ensure_one()
        caps = self._caps()
        if not caps:
            return
        now = fields.Datetime.now()
        Usage = self.env['omni.social.usage'].sudo()
        limit = caps.daily_limits.get(operation)
        if limit:
            used = Usage.search_count(
                [('connection_id', '=', self.id), ('operation', '=', operation), ('create_date', '>=', now - timedelta(hours=24))]
            )
            if used >= limit:
                raise UserError(
                    _('%(platform)s allows %(limit)s %(what)s per account in 24 hours, and that limit is reached. '
                      'Publish later; the approval stays valid until it expires.',
                      platform=caps.label, limit=format(limit, ','), what=OPERATION_LABELS.get(operation, operation))
                )
        price = self._price(operation, doc)
        if price:
            spent = sum(Usage.search([('connection_id', '=', self.id), ('create_date', '>=', _month_start(now))]).mapped('cost'))
            if spent + price > self.monthly_budget + 1e-9:
                raise UserError(
                    _('%(platform)s charges per call. This would spend $%(price).2f with $%(spent).2f of the '
                      '$%(budget).2f monthly budget already used. An account manager can raise the budget.',
                      platform=caps.label, price=price, spent=spent, budget=self.monthly_budget)
                )

    def _record_usage(self, publication, doc):
        self.ensure_one()
        internal(self.env['omni.social.usage']).sudo().create(
            {
                'connection_id': self.id,
                'publication_id': publication.id,
                'operation': publication.operation,
                'cost': self._price(publication.operation, doc),
            }
        )


class Publication(models.Model):
    _inherit = 'omni.social.publication'

    def _document(self, media_token):
        doc = super()._document(media_token)
        caps = self.connection_id._caps()
        if caps and caps.title_limit and self.operation == 'post':
            # Platforms that show a title use the subject; the approver reviews it with the rest.
            doc['title'] = (self.name or '').strip()[:caps.title_limit]
        return doc


class OAuthState(models.Model):
    """One pending sign-in: random state (stored hashed), PKCE verifier, expiry."""

    _name = 'omni.social.oauth.state'
    _description = 'Social Sign-in Attempt'
    connection_id = fields.Many2one('omni.social.connection', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', required=True, ondelete='cascade')
    state_hash = fields.Char(required=True, index=True)
    verifier = fields.Char()
    redirect_uri = fields.Char(required=True)
    account = fields.Char()
    expires_at = fields.Datetime(required=True)

    @api.model_create_multi
    def create(self, values):
        if not trusted(self):
            raise AccessError(_('Sign-in attempts are server-owned.'))
        return super().create(values)

    def write(self, values):
        raise AccessError(_('Sign-in attempts are server-owned.'))

    @api.model
    def _consume(self, state):
        """Return and delete the caller's matching, unexpired attempt."""
        if not isinstance(state, str) or not 20 <= len(state) <= 200:
            return self.browse()
        row = self.sudo().search(
            [('state_hash', '=', _hash(state)), ('user_id', '=', self.env.uid)], limit=1
        )
        if not row:
            return self.browse()
        values = row.read(['connection_id', 'verifier', 'redirect_uri', 'account', 'expires_at'])[0]
        row.unlink()
        if values['expires_at'] <= fields.Datetime.now():
            return self.browse()
        return values

    @api.autovacuum
    def _gc_expired(self):
        self.sudo().search([('expires_at', '<', fields.Datetime.now() - timedelta(hours=1))]).unlink()


class Usage(models.Model):
    _name = 'omni.social.usage'
    _description = 'Social Platform Usage'
    _order = 'create_date desc,id desc'
    connection_id = fields.Many2one('omni.social.connection', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='connection_id.company_id', store=True)
    purpose_id = fields.Many2one(related='connection_id.purpose_id', store=True)
    publication_id = fields.Many2one('omni.social.publication', ondelete='set null')
    operation = fields.Selection(
        [('post', 'Post'), ('reply', 'Public reply'), ('message', 'Private reply'), ('read', 'Reading activity')],
        required=True,
    )
    cost = fields.Float(string='Cost (USD)')

    @api.model_create_multi
    def create(self, values):
        if not trusted(self):
            raise AccessError(_('Usage is recorded by publishing.'))
        return super().create(values)

    def write(self, values):
        raise AccessError(_('Usage records are permanent.'))

    def unlink(self):
        if not trusted(self):
            raise AccessError(_('Usage records are permanent.'))
        return super().unlink()


class ChannelType(models.Model):
    _inherit = 'omni.channel.type'

    social_ready = fields.Boolean(
        compute='_compute_social_ready', search='_search_social_ready', string='Connected in Social Marketing'
    )

    def _compute_social_ready(self):
        names = set(installed(self.env))
        for row in self:
            row.social_ready = row.code in names


class Channel(models.Model):
    _inherit = 'omni.channel'

    social_platforms = fields.Char(compute='_compute_social_platforms')

    def _compute_social_platforms(self):
        labels = [capabilities(name).label for name in installed(self.env)]
        text = ', '.join(labels)
        for row in self:
            row.social_platforms = text
