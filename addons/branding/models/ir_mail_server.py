from odoo import models

from ..constants import INLINE_LOGO_CID, INLINE_LOGO_FILENAME, INLINE_LOGO_SRC


class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    def _build_email__(
        self,
        email_from,
        email_to,
        subject,
        body,
        email_cc=None,
        email_bcc=None,
        reply_to=False,
        attachments=None,
        message_id=None,
        references=None,
        object_id=False,
        subtype='plain',
        headers=None,
        body_alternative=None,
        subtype_alternative='plain',
    ):
        attachments = list(attachments or [])
        inline_logo = next(
            (attachment for attachment in attachments if attachment[0] == INLINE_LOGO_FILENAME),
            None,
        )
        should_inline_logo = inline_logo and subtype == 'html' and INLINE_LOGO_SRC in (body or '')
        if should_inline_logo:
            attachments.remove(inline_logo)

        message = super()._build_email__(
            email_from=email_from,
            email_to=email_to,
            subject=subject,
            body=body,
            email_cc=email_cc,
            email_bcc=email_bcc,
            reply_to=reply_to,
            attachments=attachments,
            message_id=message_id,
            references=references,
            object_id=object_id,
            subtype=subtype,
            headers=headers,
            body_alternative=body_alternative,
            subtype_alternative=subtype_alternative,
        )
        if should_inline_logo:
            filename, content, mimetype = inline_logo
            maintype, image_subtype = mimetype.split('/', maxsplit=1)
            html_part = message.get_body(preferencelist=('html',))
            html_part.add_related(
                getattr(content, 'content', content),
                maintype=maintype,
                subtype=image_subtype,
                cid=f'<{INLINE_LOGO_CID}>',
                filename=filename.removesuffix('.inline.png') + '.png',
                disposition='inline',
            )
        return message
