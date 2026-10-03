from odoo import api, fields, models


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    email_layout_force_footer = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('email_layout_force_footer', True)
        return super().create(vals_list)

    def send_mail_batch(
        self,
        res_ids,
        force_send=False,
        raise_exception=False,
        email_values=None,
        email_layout_xmlid=False,
    ):
        return super(MailTemplate, self.with_context(
            email_notification_force_footer=True,
        )).send_mail_batch(
            res_ids,
            force_send=force_send,
            raise_exception=raise_exception,
            email_values=email_values,
            email_layout_xmlid=email_layout_xmlid,
        )
