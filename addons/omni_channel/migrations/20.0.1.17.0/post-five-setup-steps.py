"""Drop redundant Team & apps progress without completing any unfinished step."""
from psycopg2.extras import Json


def map_completed(count, ids):
    previous = list(range(count)) if ids is None or ids is False else ids
    return sorted({4 if step == 5 else step for step in previous if type(step) is int and 0 <= step <= 5 and step != 4})


def migrate(cr, version):
    marker = 'omni_channel.setup_five_steps_migrated'
    cr.execute('SELECT value FROM ir_config_parameter WHERE key = %s', [marker])
    if cr.fetchone():
        return
    cr.execute('SELECT id, setup_completed_steps, setup_completed_step_ids FROM omni_channel')
    for channel_id, count, ids in cr.fetchall():
        completed = map_completed(count, ids)
        cr.execute('UPDATE omni_channel SET setup_completed_steps = %s, setup_completed_step_ids = %s WHERE id = %s',
                   [len(completed), Json(completed), channel_id])
    cr.execute("INSERT INTO ir_config_parameter (key, value) VALUES (%s, '1')", [marker])
