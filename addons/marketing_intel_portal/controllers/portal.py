"""Client portal for marketing: brands, campaigns with results, proofs and requests.

Portal users have no access rights on marketing records: every page reads with sudo after checking that the
logged-in contact is one of the brand's client contacts, and shows only what is listed here (no budgets or
internal notes).
"""

from datetime import timedelta
from urllib.parse import urlencode

from werkzeug.exceptions import NotFound

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.tools import plaintext2html

from odoo.addons.portal.controllers.portal import CustomerPortal

RESULTS = [('result_sent', 'Sent'), ('result_opened', 'Opened'), ('result_clicks', 'Clicked'),
           ('result_replied', 'Replies'), ('result_likes', 'Likes'), ('result_comments', 'Comments'),
           ('result_registrations', 'Registrations')]


class MarketingPortal(CustomerPortal):

    def _prepare_portal_counter_values(self, counter):
        if counter == 'mi_brand_count':
            return 'mi.brand', [('portal_partner_ids', 'in', request.env.user.partner_id.ids)], 'sudo'
        return super()._prepare_portal_counter_values(counter)

    # -- access ---------------------------------------------------------------------------------------------------
    def _partner(self):
        return request.env.user.partner_id

    def _brands(self):
        return request.env['mi.brand']._portal_brands(self._partner())

    def _brand(self, brand_id):
        brand = request.env['mi.brand'].sudo().browse(int(brand_id)).exists()
        if not brand or self._partner() not in brand.portal_partner_ids:
            raise NotFound()
        return brand

    def _plan(self, plan_id):
        plan = request.env['mi.plan'].sudo().browse(int(plan_id)).exists()
        if not plan or plan.is_template or self._partner() not in plan.brand_id.portal_partner_ids:
            raise NotFound()
        return plan

    def _proof(self, proof_id):
        proof = request.env['mi.proof'].sudo().browse(int(proof_id)).exists()
        if not proof or self._partner() not in proof.brand_id.portal_partner_ids:
            raise NotFound()
        return proof

    # -- values ---------------------------------------------------------------------------------------------------
    @staticmethod
    def _totals(plans):
        totals = []
        for field, label in RESULTS:
            value = sum(item[field] for item in plans.item_ids)
            if value:
                totals.append((label, value))
        return totals

    def _plan_rows(self, plans):
        rows = []
        for plan in plans:
            rows.append({'plan': plan, 'status': dict(plan._fields['status']._description_selection(request.env))[
                plan.status], 'progress': int(100 * plan.channels_out / plan.channel_count) if plan.channel_count else 0,
                'totals': self._totals(plan)})
        return rows

    def _layout(self, **values):
        base = self._prepare_portal_layout_values()
        base.update(values)
        base['page_name'] = 'marketing'
        return base

    # -- pages ----------------------------------------------------------------------------------------------------
    @http.route(['/my/marketing'], type='http', auth='user', website=True)
    def portal_marketing(self, **kw):
        brands = self._brands()
        if len(brands) == 1:
            return request.redirect('/my/marketing/brand/%s' % brands.id)
        return request.render('marketing_intel_portal.portal_brands', self._layout(brands=brands))

    @http.route(['/my/marketing/brand/<int:brand_id>'], type='http', auth='user', website=True)
    def portal_brand(self, brand_id, **kw):
        brand = self._brand(brand_id)
        Plan = request.env['mi.plan'].sudo()
        since = fields.Date.context_today(Plan) - timedelta(days=90)
        plans = Plan.search([('brand_id', '=', brand.id), ('is_template', '=', False), ('state', '!=', 'cancelled'),
                             '|', ('state', 'not in', ('done',)), ('date_end', '>=', since)], order='date_start desc')
        proofs = request.env['mi.proof'].sudo().search([('brand_id', '=', brand.id), ('client_review', '=', True),
                                                       ('state', 'in', ('review', 'changes', 'approved'))],
                                                      order='write_date desc', limit=20)
        requests_ = request.env['mi.request'].sudo().search([('brand_id', '=', brand.id),
                                                            ('requested_by', '=', self._partner().id)],
                                                           order='create_date desc', limit=20)
        to_sign = plans.filtered(lambda p: p.client_state == 'waiting')
        return request.render('marketing_intel_portal.portal_brand', self._layout(
            brand=brand, rows=self._plan_rows(plans), totals=self._totals(plans.filtered(lambda p: p.state != 'brief')),
            proofs=proofs, proofs_waiting=proofs.filtered(lambda p: p.state == 'review'), to_sign=to_sign,
            client_requests=requests_, message=kw.get('message')))

    @http.route(['/my/marketing/campaign/<int:plan_id>'], type='http', auth='user', website=True)
    def portal_campaign(self, plan_id, **kw):
        plan = self._plan(plan_id)
        channels = dict(plan.item_ids._fields['channel']._description_selection(request.env))
        stages = dict(plan.item_ids._fields['stage']._description_selection(request.env))
        items = [{'item': item, 'channel': channels.get(item.channel), 'stage': stages.get(item.stage),
                  'results': [(label, item[field]) for field, label in RESULTS if item[field]],
                  'subject': item._content()[0], 'text': item._content()[1]} for item in plan.item_ids]
        return request.render('marketing_intel_portal.portal_campaign', self._layout(
            plan=plan, brand=plan.brand_id, row=self._plan_rows(plan)[0], items=items,
            proofs=plan.proof_ids.filtered(lambda p: p.client_review and p.state != 'old'),
            error=kw.get('error'), message=kw.get('message')))

    @http.route(['/my/marketing/campaign/<int:plan_id>/decision'], type='http', auth='user', website=True,
                methods=['POST'])
    def portal_campaign_decision(self, plan_id, decision=None, feedback='', **kw):
        plan = self._plan(plan_id)
        try:
            plan._client_decide(self._partner(), decision == 'approve', feedback)
        except (UserError, AccessError) as error:
            return request.redirect('/my/marketing/campaign/%s' % plan.id + '?' + urlencode({'error': str(error)}))
        return request.redirect('/my/marketing/campaign/%s' % plan.id + '?' + urlencode({'message': _('Thank you, your decision is saved.')}))

    @http.route(['/my/marketing/proof/<int:proof_id>'], type='http', auth='user', website=True)
    def portal_proof(self, proof_id, **kw):
        proof = self._proof(proof_id)
        if not proof.client_review:
            raise NotFound()
        return request.render('marketing_intel_portal.portal_proof', self._layout(
            proof=proof, brand=proof.brand_id, error=kw.get('error'), message=kw.get('message')))

    @http.route(['/my/marketing/proof/<int:proof_id>/decision'], type='http', auth='user', website=True,
                methods=['POST'])
    def portal_proof_decision(self, proof_id, decision=None, feedback='', **kw):
        proof = self._proof(proof_id)
        try:
            proof._client_decide(self._partner(), decision == 'approve', feedback)
        except (UserError, AccessError) as error:
            return request.redirect('/my/marketing/proof/%s' % proof.id + '?' + urlencode({'error': str(error)}))
        return request.redirect('/my/marketing/proof/%s' % proof.id + '?' + urlencode({'message': _('Thank you, your decision is saved.')}))

    @http.route(['/my/marketing/brand/<int:brand_id>/request'], type='http', auth='user', website=True,
                methods=['GET', 'POST'])
    def portal_request(self, brand_id, **post):
        brand = self._brand(brand_id)
        if request.httprequest.method == 'POST':
            name = (post.get('name') or '').strip()
            if not name:
                return request.render('marketing_intel_portal.portal_request', self._layout(
                    brand=brand, error=_('Say what you need.'), values=post))
            wanted = post.get('wanted_by') or False
            try:
                wanted = fields.Date.to_date(wanted) if wanted else False
            except ValueError:
                wanted = False
            request.env["mi.request"].sudo().create({
                'name': name[:200], 'brand_id': brand.id, 'requested_by': self._partner().id, 'from_portal': True,
                'goal': post.get('goal'), 'audience': post.get('audience'), 'wanted_by': wanted,
                'description': plaintext2html(post['details']) if post.get('details') else False,
            })
            return request.redirect('/my/marketing/brand/%s' % brand.id + '?' + urlencode({'message': _('Your request was sent.')}))
        return request.render('marketing_intel_portal.portal_request', self._layout(brand=brand, values={}))
