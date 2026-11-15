def migrate(cr, version):
    """Assistants' avatars changed again (the stars are no longer drawn in the picture; Discuss lays them over its
    top right corner): mark the assistants' chat partners as changed, so browsers fetch the new avatar instead of
    the one they kept."""
    cr.execute("UPDATE res_partner SET write_date = (now() AT TIME ZONE 'UTC') WHERE ai_agent_partner")
