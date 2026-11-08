"""The ERP's own local Hermes: a separate Hermes home, never the operator's personal one.

    python3 erp_hermes.py provision   # once: config and private keys in the ERP home
    python3 erp_hermes.py start       # gateway (multiplexed profiles) and dashboard/management API
    python3 erp_hermes.py stop
    python3 erp_hermes.py status

The home is ``$HERMES_ERP_HOME`` (default ``~/hermes-erp``). The gateway listens on 127.0.0.1:8643 and serves every
profile the ERP creates at ``/p/<profile>/v1/...``; the dashboard and management API listen on 127.0.0.1:9120. Only
ERP profiles live in this home: no messaging platforms, memory off, no Hermes toolsets. The model provider is chosen
by the operator once, in the dashboard (Models page) or with ``hermes login`` using this home. No credential is
printed or passed on a command line.
"""
import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path

INSTALL = Path(os.environ.get('HERMES_INSTALL', '/mnt/agent/hermes-agent'))
HOME = Path(os.environ.get('HERMES_ERP_HOME', Path.home() / 'hermes-erp'))
GATEWAY_PORT, DASHBOARD_PORT = 8643, 9120
MARKER = HOME / '.erp-provisioned'

CONFIG = f"""# The ERP's own Hermes home (ai_agent/deployment/erp_hermes.py). Profiles are created by the ERP.
platform_toolsets:
  api_server: []
  cli: []
  dashboard: []
memory:
  memory_enabled: false
  user_profile_enabled: false
  provider: ""
skills:
  write_approval: true
mcp_servers: {{}}
agent:
  max_turns: 20
gateway:
  multiplex_profiles: true
  api_server:
    enabled: true
    host: 127.0.0.1
    port: {GATEWAY_PORT}
    max_concurrent_runs: 2
platforms:
  api_server:
    enabled: true
    extra:
      host: 127.0.0.1
      port: {GATEWAY_PORT}
"""


def _env():
    values = {}
    for line in (HOME / '.env').read_text().splitlines():
        name, separator, value = line.partition('=')
        if separator and name and not name.startswith('#'):
            values[name.strip()] = value.strip()
    return values


def _python():
    """Hermes's venv targets Python 3.12; its own interpreter link may point elsewhere."""
    packages = INSTALL / 'venv' / 'lib' / 'python3.12' / 'site-packages'
    return '/usr/bin/python3.12', str(packages)


def provision():
    if MARKER.exists():
        raise SystemExit(f'{HOME} is already provisioned; keys are not rotated implicitly.')
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    (HOME / 'config.yaml').write_text(CONFIG)
    env_path = HOME / '.env'
    env_path.write_text(''.join(f'{name}={value}\n' for name, value in {
        'API_SERVER_ENABLED': 'true', 'API_SERVER_HOST': '127.0.0.1', 'API_SERVER_PORT': str(GATEWAY_PORT),
        'API_SERVER_KEY': secrets.token_urlsafe(40),
        'HERMES_DASHBOARD_SESSION_TOKEN': secrets.token_urlsafe(40)}.items()))
    env_path.chmod(0o600)
    (HOME / 'SOUL.md').write_text('You are an assistant of the company ERP. Profiles add their own persona.\n')
    MARKER.write_text('The ERP\'s own Hermes home.\n')
    print(f'Provisioned {HOME}. Keys saved privately in {env_path}; none were printed.')
    print('Next: choose the model provider (dashboard Models page, or hermes login with this home), then start.')


def _pids():
    pids = {}
    for kind in ('gateway', 'dashboard'):
        path = HOME / f'erp-{kind}.pid'
        if path.exists():
            pid = int(path.read_text())
            try:
                os.kill(pid, 0)
                pids[kind] = pid
            except ProcessLookupError:
                path.unlink()
    return pids


def start():
    if not MARKER.exists():
        raise SystemExit('Run "provision" first.')
    running = _pids()
    python, packages = _python()
    keep = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
            'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'no_proxy')
    # Nothing from the caller's Hermes (its HERMES_HOME, keys or platforms) reaches this home's processes.
    env = {name: value for name, value in os.environ.items() if name in keep}
    env.update(_env())
    env.update({'HERMES_HOME': str(HOME), 'PYTHONPATH': packages})
    commands = {'gateway': ['gateway', 'run', '--no-supervise'],
                'dashboard': ['dashboard', '--host', '127.0.0.1', '--port', str(DASHBOARD_PORT), '--skip-build',
                              '--no-open']}
    with (HOME / 'erp-hermes.log').open('ab') as log:
        for kind, args in commands.items():
            if kind in running:
                print(f'{kind} already running (PID {running[kind]}).')
                continue
            process = subprocess.Popen([python, str(INSTALL / 'hermes'), *args], cwd=INSTALL, env=env,
                                       stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
            (HOME / f'erp-{kind}.pid').write_text(str(process.pid))
            print(f'{kind} started (PID {process.pid}); log: {HOME / "erp-hermes.log"}')


def stop():
    for kind, pid in _pids().items():
        os.killpg(pid, signal.SIGTERM)
        (HOME / f'erp-{kind}.pid').unlink(missing_ok=True)
        print(f'{kind} stopped (PID {pid}).')


def status():
    running = _pids()
    for kind in ('gateway', 'dashboard'):
        print(f'{kind}: ' + (f'running (PID {running[kind]})' if kind in running else 'stopped'))


if __name__ == '__main__':
    actions = {'provision': provision, 'start': start, 'stop': stop, 'status': status}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise SystemExit(__doc__)
    actions[sys.argv[1]]()
