"""Bounded use of the existing KenPulse model owner, under KenRadar's GPU lock.

No model installation, subprocess management, or Ollama compatibility guesses.
"""
from contextlib import contextmanager
import time
from urllib.parse import urlsplit

import requests

CONTROL = 'http://127.0.0.1:9377'
MODEL = 'qwen3.8-flash-next-iq2_xs'


def _snapshot():
    response = requests.get(CONTROL + '/api/status', timeout=10)
    response.raise_for_status()
    return response.json()['strata']


def _action(action):
    response = requests.get(CONTROL + '/api/token', timeout=10)
    response.raise_for_status()
    token = response.json()['token']
    response = requests.post(
        CONTROL + '/api/strata/action',
        headers={'X-KenPulse-Token': token, 'Origin': CONTROL},
        json={'action': action, 'model': 'IQ2_XS'}, timeout=15,
    )
    response.raise_for_status()


@contextmanager
def managed_strata(provider, gpu):
    endpoint = urlsplit(str(provider.get('endpoint', '')))
    if endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1' or endpoint.port != 8080 or provider.get('model') != MODEL:
        raise RuntimeError('Managed Strata requires the installed loopback IQ2 endpoint/model')
    with gpu.gpu_task('strata:' + MODEL):
        before = _snapshot()
        if before.get('busy') or before.get('state') not in {'stopped', 'ready'}:
            raise RuntimeError('Strata is busy, unavailable or owned by another operation')
        owned = before.get('state') == 'stopped' and not before.get('desired')
        if before.get('state') == 'stopped' and not owned:
            raise RuntimeError('Strata has an existing recovery owner')
        try:
            if owned:
                _action('start')
                deadline = time.monotonic() + max(1, min(600, float(provider.get('startup_timeout', 600))))
                while True:
                    state = _snapshot()
                    if state.get('state') == 'ready' and not state.get('busy'):
                        break
                    if state.get('state') in {'error', 'conflict'}:
                        raise RuntimeError('Strata startup failed')
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Strata startup timeout')
                    time.sleep(1)
            health = requests.get('http://127.0.0.1:8080/health', timeout=10)
            health.raise_for_status()
            value = health.json()
            if not value.get('loaded') or value.get('model') != MODEL:
                raise RuntimeError('Strata model identity mismatch')
            yield
        finally:
            if owned:
                # The owner API performs asynchronous starts/stops. Do not race
                # its busy operation or leave desired=true recovery resident.
                deadline = time.monotonic() + 45
                while _snapshot().get('busy'):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Strata cleanup blocked by busy owner')
                    time.sleep(1)
                _action('stop')
                while True:
                    state = _snapshot()
                    if state.get('state') == 'stopped' and not state.get('desired') and not state.get('busy'):
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Strata cleanup timeout')
                    time.sleep(1)
