def migrate(cr, version):
    """Assistants' avatars changed (stars at the top right). Browsers keep an avatar for as long as the partner's
    last change stays the same, so mark the assistants' chat partners as changed: everyone gets the new avatar."""
    cr.execute("UPDATE res_partner SET write_date = (now() AT TIME ZONE 'UTC') WHERE ai_agent_partner")
