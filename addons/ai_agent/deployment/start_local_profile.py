"""Start only the explicitly approved isolated Hermes profile, without systemd."""
import os
from pathlib import Path
import subprocess

from dotenv import dotenv_values

INSTALL = Path('/mnt/agent/hermes-agent')
ROOT = Path('/mnt/agent')
PROFILE = ROOT / 'profiles' / 'odoo-internal'
if not (PROFILE / '.odoo-provisioned').exists():
    raise SystemExit('Provision the reviewed isolated profile first.')
for filename in ('odoo-gateway.pid', 'odoo-management.pid'):
    pidfile = PROFILE / filename
    if pidfile.exists():
        pid = int(pidfile.read_text())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise SystemExit('A tracked profile service is already running; no duplicate start.')
# Native -p selection loads this profile only; do not inherit messaging keys or
# old Hermes runtime settings from the caller.
child_env = {k: v for k, v in os.environ.items() if k in (
    'PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
    'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'no_proxy')}
child_env.update({k: v for k, v in dotenv_values(PROFILE / '.env').items() if v is not None})
child_env['HERMES_HOME'] = str(ROOT)
python, hermes = INSTALL / 'venv' / 'bin' / 'python', INSTALL / 'hermes'
with (PROFILE / 'odoo-startup.log').open('ab') as log:
    for kind, args in [('gateway', ['gateway', 'run']),
                       ('management', ['serve', '--host', '127.0.0.1', '--port', '9120', '--isolated'])]:
        process = subprocess.Popen([str(python), str(hermes), '-p', 'odoo-internal', *args],
            cwd=INSTALL, env=child_env, stdout=log, stderr=log, start_new_session=True)
        (PROFILE / f'odoo-{kind}.pid').write_text(str(process.pid))
        print(kind, 'start requested; PID', process.pid)
