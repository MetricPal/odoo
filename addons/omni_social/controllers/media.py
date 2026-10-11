"""Serve only the immutable JPEG belonging to a current publishing claim."""
import hashlib
import re
from odoo import http, fields
from odoo.http import request
class SocialMedia(http.Controller):
    @http.route('/omni/social/media/<token>',type='http',auth='public',methods=['GET'],csrf=False)
    def image(self,token,**kw):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token): return request.not_found()
        row=request.env['omni.social.publication'].sudo().search([('media_token','=',token),
            ('state','in',['executing','waiting']),('expires_at','>',fields.Datetime.now())],limit=1)
        if not row or not row.connection_id.active or row.payload.get('revision')!=row.connection_id.revision or not row.image: return request.not_found()
        raw=row.image.content
        if hashlib.sha256(raw).hexdigest()!=row.payload.get('image_digest'): return request.not_found()
        return request.make_response(raw,headers=[('Content-Type','image/jpeg'),('Content-Length',str(len(raw))),
            ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')])
