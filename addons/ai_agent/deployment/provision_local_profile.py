"""Operator provisioning for the explicitly approved local odoo-internal profile.

Run with the installed Hermes interpreter. No credentials are printed or passed
on command lines. This script never changes the existing profile or its services.
"""
import os
from pathlib import Path
import secrets
import sys

import yaml
from dotenv import dotenv_values

INSTALL = Path('/mnt/agent/hermes-agent')
ROOT = Path('/mnt/agent')
PROFILE = ROOT / 'profiles' / 'odoo-internal'
if not (PROFILE / '.no-bundled-skills').exists():
    raise SystemExit('Create the new no-skills profile with Hermes first.')
if (PROFILE / '.odoo-provisioned').exists():
    raise SystemExit('Profile already provisioned; do not rotate or repeat implicitly.')
root_config = yaml.safe_load((ROOT / 'config.yaml').read_text()) or {}
model = root_config.get('model')
if not isinstance(model, dict) or not model.get('default'):
    raise SystemExit('Existing model selection needs explicit configuration.')
# Copy only the selected inference endpoint. No channels, cron, memory, skills,
# SOUL, histories, external tool credentials or unrelated root configuration.
selected_model = {k: model[k] for k in ('default', 'provider', 'base_url', 'api_mode', 'context_length') if k in model}
root_env = dotenv_values(ROOT / '.env')
provider = selected_model.get('provider', 'auto')
provider_names = {'openrouter': ('OPENROUTER_API_KEY',), 'openai': ('OPENAI_API_KEY',),
                  'anthropic': ('ANTHROPIC_API_KEY', 'ANTHROPIC_TOKEN'),
                  'google': ('GEMINI_API_KEY',), 'gemini': ('GEMINI_API_KEY',)}
config = yaml.safe_load((Path(__file__).parent / 'local-profile.yaml').read_text())
config['model'] = selected_model
os.environ['HERMES_HOME'] = str(PROFILE)
sys.path.insert(0, str(INSTALL))
from hermes_cli.config import save_config, save_env_value, get_config_path, get_env_path
if Path(get_config_path()).parent != PROFILE or Path(get_env_path()).parent != PROFILE:
    raise SystemExit('Hermes profile path mismatch; refusing configuration.')
save_config(config, strip_defaults=False)
for name in provider_names.get(provider, ()):
    if root_env.get(name):
        save_env_value(name, root_env[name])
# Current custom endpoint has no configured provider credential. It is retained
# as selected, not replaced with an invented provider or an copied auth session.
run_key, management_key = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
for name, value in {'API_SERVER_ENABLED': 'true', 'API_SERVER_HOST': '127.0.0.1',
                    'API_SERVER_PORT': '8643', 'API_SERVER_KEY': run_key,
                    'HERMES_DASHBOARD_SESSION_TOKEN': management_key,
                    'AI_AGENT_SECRET_ODOO_RUN': run_key,
                    'AI_AGENT_SECRET_ODOO_MANAGEMENT': management_key}.items():
    save_env_value(name, value)
Path(get_env_path()).chmod(0o600)
(PROFILE / '.odoo-provisioned').write_text('Approved isolated Odoo internal assistant profile.\n')
print('Provisioned isolated odoo-internal profile.')
print('Credentials saved privately in the new profile; none were printed.')
