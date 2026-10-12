"""Open a dedicated login window and save only Douyin cookies locally."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import yaml

from kenradar.core.config import load_config, save_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/config.yaml')
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    config = load_config(args.config)
    from playwright.sync_api import sync_playwright
    candidates = [Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
                  Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe']
    executable = next((p for p in candidates if p.is_file()), None)
    if executable is None:
        raise RuntimeError('Chrome or Edge is required')
    status = config.data_dir / 'setup/douyin-login-status.json'
    status.parent.mkdir(parents=True, exist_ok=True)

    def record(state, **details):
        status.write_text(json.dumps({'state': state, **details}, ensure_ascii=False), encoding='utf-8')

    record('waiting_for_user_login')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(executable), headless=False)
        try:
            context = browser.new_context(locale='zh-CN', viewport={'width': 1280, 'height': 850})
            page = context.new_page()
            page.goto('https://www.douyin.com/', wait_until='domcontentloaded', timeout=60000)
            print('Dedicated Douyin login window opened. Complete login in that window.', flush=True)
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                if page.is_closed():
                    record('cancelled')
                    return
                cookies = context.cookies()
                douyin = [c for c in cookies if c['domain'].lstrip('.') == 'douyin.com' or c['domain'].endswith('.douyin.com')]
                sessions = [c for c in douyin if c['name'] in {'sessionid', 'sessionid_ss'} and c['value']]
                if sessions:
                    # Prefer the root-domain value when the same name occurs twice.
                    douyin.sort(key=lambda c: c['domain'].lstrip('.') == 'douyin.com')
                    values = {c['name']: c['value'] for c in douyin if c['value']}
                    target = config.root_dir / 'config/douyin.cookies.yaml'
                    if target.exists():
                        backup = target.with_name(target.name + f'.{int(time.time())}.bak')
                        with backup.open('x', encoding='utf-8') as stream:
                            stream.write(target.read_text(encoding='utf-8'))
                    temporary = target.with_name(target.name + '.login.tmp')
                    with temporary.open('x', encoding='utf-8') as stream:
                        yaml.safe_dump(values, stream, allow_unicode=True)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, target)
                    fresh = load_config(args.config)
                    fresh.raw.setdefault('app', {})['douyin_cookie_file'] = 'config/douyin.cookies.yaml'
                    save_config(fresh)
                    effective = load_config(args.config).cookies
                    if not effective.get('sessionid') and not effective.get('sessionid_ss'):
                        record('configuration_override_requires_review', cookie_count=len(values))
                        raise RuntimeError('Cookie file saved but another environment configuration overrides it')
                    record('saved', cookie_count=len(values), authentication_verified=False)
                    print('Douyin cookies saved locally. No cookie values are printed; collection remains disabled.', flush=True)
                    return
                page.wait_for_timeout(2000)
            record('timed_out')
            print('Login timed out; no cookies saved.', flush=True)
        except Exception:
            record('error')
            raise RuntimeError('Douyin login could not complete; cookie values are withheld') from None
        finally:
            browser.close()


if __name__ == '__main__':
    main()
