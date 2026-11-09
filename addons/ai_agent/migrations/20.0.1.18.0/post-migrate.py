def migrate(cr, version):
    # Runs asked before 20.0.1.18.0 get the Hermes connection of their agent (Activity: group by Hermes connection).
    cr.execute("""
        UPDATE ai_agent_run r
           SET engine_id = a.engine_id
          FROM ai_agent a
         WHERE a.id = r.agent_id AND r.engine_id IS NULL
    """)
