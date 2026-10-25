def migrate(cr, version):
    # Brands that already had a client contact were client brands.
    cr.execute("UPDATE mi_brand SET owner_type = 'client' WHERE partner_id IS NOT NULL AND owner_type = 'own'")
    if cr.rowcount:
        from odoo import api, SUPERUSER_ID
        env = api.Environment(cr, SUPERUSER_ID, {})
        brands = env['mi.brand'].search([('partner_id', '!=', False)])
        env.add_to_compute(brands._fields['portfolio'], brands)
        env.flush_all()
