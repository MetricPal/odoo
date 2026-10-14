def migrate(cr, version):
    # Preserve existing department audiences under the combined scope.
    cr.execute("UPDATE ai_agent SET access_scope = 'users' WHERE access_scope = 'departments'")
