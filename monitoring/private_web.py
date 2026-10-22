#!/usr/bin/env python3
"""Add/remove only a dedicated private Tailscale Serve listener on port 8443."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from run_monitor import HOME, MonitorError, atomic, load_config, now


TARGET = 'http://127.0.0.1:8788'


def command(*args):
    try:
        result = subprocess.run(['sudo', 'tailscale', *args], capture_output=True, text=True, timeout=30, check=True)
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise MonitorError('Could not read Tailscale state. Check sudo/Tailscale locally; no Serve change was made by this read.') from None


def mentions_port(obj, port='8443'):
    if isinstance(obj, dict):
        return any((str(key) == port or str(key).endswith(':' + port)) or mentions_port(value, port) for key, value in obj.items())
    if isinstance(obj, list):
        return any(mentions_port(value, port) for value in obj)
    return False


def own_listener(state, hostname):
    listener = state.get('Web', {}).get(hostname + ':8443', {})
    handlers = listener.get('Handlers', {})
    tcp = state.get('TCP', {}).get('8443', {})
    funnel = state.get('AllowFunnel', {}).get(hostname + ':8443', False)
    return (tcp.get('HTTPS') is True and not funnel and set(handlers) == {'/'}
            and handlers['/'].get('Proxy') == TARGET)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('enable', 'disable'))
    args = parser.parse_args()
    try:
        config = load_config(HOME)
        hostname = urlsplit(config['public_origin']).hostname
        actual = command('status', '--json').get('Self', {}).get('DNSName', '').rstrip('.')
        if actual.lower() != hostname.lower():
            raise MonitorError('Configured dashboard host differs from this node Tailscale DNS name')
        state = command('serve', 'status', '--json')
        if args.action == 'enable':
            if own_listener(state, hostname):
                print('Private listener already configured: ' + config['public_origin'])
                return 0
            if mentions_port(state):
                raise MonitorError('Port 8443 already appears in Serve configuration. It was not overwritten. Inspect tailscale serve status.')
            backup = HOME / 'serve-backups' / (now().replace(':', '-') + '.json')
            atomic(backup, state)
            # Serve is tailnet-only. Never use Funnel or reset the existing configuration.
            subprocess.run(['sudo', 'tailscale', 'serve', '--bg', '--https=8443', TARGET], check=True)
            if not own_listener(command('serve', 'status', '--json'), hostname):
                raise MonitorError('Serve command returned, but the dedicated listener could not be verified. Inspect tailscale serve status.')
            print('Private run history: ' + config['public_origin'])
            print('Connect your phone to Tailscale, then sign in with your dashboard password.')
        else:
            if not mentions_port(state):
                print('No 8443 listener exists; nothing changed.')
                return 0
            if not own_listener(state, hostname):
                raise MonitorError('Port 8443 no longer matches this monitor. No listener was removed.')
            subprocess.run(['sudo', 'tailscale', 'serve', '--bg', '--https=8443', 'off'], check=True)
            print('Dedicated monitor listener removed; existing 443 Serve routes were retained.')
        return 0
    except (MonitorError, subprocess.SubprocessError) as exc:
        print('ERROR: ' + (str(exc) if isinstance(exc, MonitorError) else 'Tailscale command did not complete; inspect Serve status before retrying.'))
        return 1


if __name__ == '__main__':
    sys.exit(main())
