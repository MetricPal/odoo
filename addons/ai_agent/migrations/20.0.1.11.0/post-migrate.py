def migrate(cr, version):
    """Profiles synced before ``in_hermes`` existed: those with a run key or a successful sync are in Hermes."""
    cr.execute("""
        UPDATE ai_agent_profile
           SET in_hermes = TRUE
         WHERE state IN ('in_sync', 'needs_sync')
            OR secret_reference LIKE 'AI_AGENT_SECRET_RUNTIME_%'
    """)
