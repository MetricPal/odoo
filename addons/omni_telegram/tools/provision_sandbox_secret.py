"""Enter a rotated sandbox token privately; never pass it as a command argument."""
import argparse
import getpass
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path


def provision(path, database, company_id, bot_id, token):
    if not re.fullmatch(r'[1-9][0-9]{0,15}', bot_id) or not re.fullmatch(re.escape(bot_id) + r':[A-Za-z0-9_-]{20,128}', token):
        message = 'The token does not match the expected bot ID or format.'
        raise ValueError(message)
    if not database or company_id <= 0:
        message = 'A database and positive company ID are required.'
        raise ValueError(message)
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        message = 'Use an existing private directory owned by your user, with mode 700.'
        raise ValueError(message)
    payload = {'database': database, 'company_id': company_id, 'bot_id': bot_id,
               'token': token, 'webhook_secret': secrets.token_urlsafe(48)}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(payload, output)
        output.flush()
        os.fsync(output.fileno())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--company-id', required=True, type=int)
    parser.add_argument('--bot-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.exit(1, 'Run this in an interactive terminal. Token input will be hidden.\n')
    try:
        provision(args.output, args.database, args.company_id, args.bot_id, getpass.getpass('Rotated bot token (hidden): '))
    except (OSError, ValueError):
        parser.exit(1, 'Provisioning failed. Check bot identity, private directory and that the output file does not already exist.\n')
    print('Secret bundle saved privately. No network request or message was sent.')  # noqa: T201 - CLI status, never secret content
