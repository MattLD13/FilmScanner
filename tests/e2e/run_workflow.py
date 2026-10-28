"""Run against the built client with real HTTP/WebSocket connections.

Usage: python tests/e2e/run_workflow.py
Uses a temporary isolated library and a headless browser; no personal archive.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

import tifffile

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
URL = 'http://127.0.0.1:8766'


def wait_server():
    for _ in range(100):
        try:
            with urllib.request.urlopen(URL + '/api/health', timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(.1)
    raise AssertionError('Temporary service failed to start')


def write_profile(folder):
    # Fictitious linear film term in the CyberView layout; no vendor profile is used.
    table = '\n'.join('\t'.join([str(i)] * 3) for i in range(256))
    folder.mkdir(parents=True)
    (folder / 'E2E Linear.ft').write_text('FilmClass\t\tNEG;\nFilmMfgr\t\tFRAME;\nFilmName\t\tE2E Linear;\n'
                                         f'FilmBalance\t\t1\t1\t1;\nFilmLut\t\t\n{table}\n', encoding='latin-1')


def run():
    evidence = ROOT / 'docs' / 'screenshots'
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='frame-browser-') as temporary:
        write_profile(Path(temporary) / 'filmterms')
        env = dict(os.environ, FRAME_DATA_DIR=str(Path(temporary) / 'library'),
                   FRAME_FILMTERM_DIRS=str(Path(temporary) / 'filmterms'))
        with (Path(temporary) / 'server.log').open('w') as log:
            service = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'services.api.main:app', '--host', '127.0.0.1', '--port', '8766'],
                                       cwd=ROOT, env=env, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                wait_server()
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    desktop = browser.new_context(viewport={'width': 1440, 'height': 1000})
                    page = desktop.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('dialog', lambda dialog: dialog.accept())
                    page.goto(URL)
                    page.wait_for_selector('main')
                    assert 'FRAME' in page.title().upper()
                    page.screenshot(path=str(evidence / 'desktop-empty.png'), full_page=True)
                    # The same local cookie scope used by the client protects real WS clients.
                    assert desktop.request.post(URL + '/api/auth/local').ok
                    page.locator('.sidebar nav button').filter(has_text='Rolls').click()
                    page.get_by_label('FILM STOCK', exact=True).fill('Browser rehearsal HP5')
                    page.get_by_label('CAMERA', exact=True).fill('Nikon FM2')
                    page.get_by_label('CAPTURE DATE', exact=True).fill('2026-10-27')
                    page.get_by_role('combobox', name=re.compile('FILM TYPE')).select_option('bw_negative')
                    page.get_by_role('button', name='Create roll ↗', exact=True).click()
                    expect(page.locator('.roll-list')).to_contain_text('Browser rehearsal HP5')
                    roll = desktop.request.get(URL + '/api/state').json()['rolls'][0]
                    page.locator('.sidebar nav button').filter(has_text='Develop').click()
                    page.get_by_role('checkbox').check()
                    page.get_by_role('button', name='Start demo session ↗', exact=True).click()
                    expect(page.locator('.timer')).to_contain_text('STEP 1 OF 3')
                    session = desktop.request.get(URL + '/api/state').json()['development'][0]
                    # Real elapsed timing, including an actual page reload in the first step.
                    time.sleep(2)
                    page.reload()
                    page.locator('.sidebar nav button').filter(has_text='Develop').click()
                    state = desktop.request.get(URL + '/api/state').json()
                    assert 0 < state['development'][0]['remaining_seconds'] < 7
                    for duration in (8, 5, 6):
                        deadline = time.monotonic() + duration + 4
                        while time.monotonic() < deadline:
                            state = desktop.request.get(URL + '/api/state').json()
                            if state['development'][0]['status'] == 'awaiting_user_transition':
                                break
                            time.sleep(.2)
                        transition = page.get_by_role('button', name='Confirm physical transition ↗', exact=True)
                        expect(transition).to_be_enabled(timeout=4000)
                        transition.click()
                        page.wait_for_timeout(200)
                    assert desktop.request.get(URL + '/api/state').json()['development'][0]['status'] == 'completed'
                    phone = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, device_scale_factor=1, has_touch=True)
                    mobile = phone.new_page()
                    mobile.goto(URL)
                    mobile.wait_for_selector('main')
                    mobile.wait_for_function('document.body.innerText.includes("LOCAL FIRST")')
                    assert phone.request.post(URL + '/api/auth/local').ok
                    mobile.evaluate("""() => {
                      window.frameEvents = [];
                      window.frameSocket = new WebSocket(`ws://${location.host}/api/events`);
                      window.frameSocket.onmessage = e => window.frameEvents.push(JSON.parse(e.data));
                    }""")
                    mobile.wait_for_function('window.frameEvents.some(e => e.type === "snapshot")')
                    mobile.locator('.mobile-nav button').filter(has_text='Scan').click()
                    page.locator('.sidebar nav button').filter(has_text='Scan').click()
                    page.get_by_role('button', name='Connect simulator ↗', exact=True).click()
                    expect(page.locator('.pill')).to_contain_text('SIMULATOR · CONNECTED')
                    # Scan workspace: profile, prescan strip, dragged scan window and channel exposure.
                    page.get_by_role('combobox', name=re.compile('FILM PROFILE')).select_option(label='E2E Linear')
                    page.get_by_role('button', name='Prescan roll ↗', exact=True).click()
                    expect(page.locator('.frame-strip [role=listitem]')).to_have_count(36)
                    expect(page.locator('.ws-viewer img')).to_be_visible()
                    page.locator('.ws-viewer').scroll_into_view_if_needed()
                    box = page.locator('.ws-viewer').bounding_box()
                    page.mouse.move(box['x'] + box['width'] * .2, box['y'] + box['height'] * .2)
                    page.mouse.down()
                    page.mouse.move(box['x'] + box['width'] * .8, box['y'] + box['height'] * .8, steps=8)
                    page.mouse.up()
                    expect(page.locator('.ws-window')).to_be_visible()
                    expect(page.get_by_label('WINDOW LEFT %', exact=True)).to_have_value('20')
                    page.locator('.ws-controls input[type=range]').first.press('ArrowRight')
                    expect(page.locator('.ws-controls')).to_contain_text('EXPOSURE R · 105%')
                    page.locator('.scan-workspace').screenshot(path=str(evidence / 'desktop-scan-workspace.png'))
                    page.get_by_role('button', name='Start simulated scan ↗', exact=True).click()
                    mobile.wait_for_function('window.frameEvents.some(e => e.type === "frame_saved")', timeout=20000)
                    received = mobile.evaluate('window.frameEvents.filter(e => e.type === "frame_saved")[0]')
                    assert received['frame']['preview_path']
                    assert received['scan']['completed_frames'] < 36
                    assert 'pixels' not in received['frame']
                    expect(mobile.locator('.scan-preview img')).to_be_visible()
                    mobile.evaluate('window.frameSocket.close()')
                    for _ in range(400):
                        state = desktop.request.get(URL + '/api/state').json()
                        if state['scan']['status'] in ('complete', 'error'):
                            break
                        time.sleep(.05)
                    assert state['scan']['status'] == 'complete', state['scan']
                    assert len(state['frames']) == 36
                    for saved in state['frames']:
                        settings = saved['scan_settings']
                        assert settings['gains'] == [1.05, 1, 1] and settings['film_profile'] == saved['edit']['film_profile']
                        assert abs(settings['window']['left'] - .2) < .02 and abs(settings['window']['width'] - .6) < .02
                        assert settings['delivered'].endswith('uint8 synthetic fixture')
                    # A companion reconnect obtains current state with paths, not image buffers.
                    mobile.evaluate("""() => {
                      window.reconnected = null;
                      window.frameSocket = new WebSocket(`ws://${location.host}/api/events`);
                      window.frameSocket.onmessage = e => { if (!window.reconnected) window.reconnected = JSON.parse(e.data); };
                    }""")
                    mobile.wait_for_function('window.reconnected !== null')
                    assert mobile.evaluate('window.reconnected.data.scan.completed_frames') == 36
                    first = state['frames'][0]
                    page.locator('.sidebar nav button').filter(has_text='Home').click()
                    expect(page.locator('.feature-image img')).to_be_visible()
                    before_shuffle = page.locator('.feature-image img').get_attribute('src')
                    page.get_by_role('button', name='SHUFFLE ↻', exact=True).click()
                    expect(page.locator('.feature-image img')).not_to_have_attribute('src', before_shuffle)
                    expect(page.locator('.feature-caption')).to_contain_text('Oct 27, 2026')
                    page.locator('.sidebar nav button').filter(has_text='Rolls').click()
                    page.get_by_label('SEARCH', exact=True).fill('2026-10-27')
                    expect(page.locator('.roll-list')).to_contain_text('Browser rehearsal HP5')
                    page.get_by_label('SEARCH', exact=True).fill('Browser rehearsal HP5')
                    expect(page.locator('.roll-list')).to_contain_text('Browser rehearsal HP5')
                    page.locator('.gallery button').first.click()
                    expect(page.locator('.editor')).to_be_visible()
                    for _ in range(4):
                        page.locator('.editor input[type=range]').first.press('ArrowRight')
                    page.locator('.editor input[type=range]').nth(1).press('ArrowRight')
                    page.locator('.editor select').select_option('90')
                    page.get_by_label('FILM BASE R', exact=True).fill('0.95')
                    page.get_by_label('FILM BASE G', exact=True).fill('0.9')
                    page.get_by_label('FILM BASE B', exact=True).fill('0.85')
                    page.get_by_role('button', name='Save edits ↗', exact=True).click()
                    expect(page.get_by_role('button', name='Save edits ↗', exact=True)).to_be_enabled()
                    # The enabled-button check can pass before the request starts; wait for the saved edit itself.
                    for _ in range(100):
                        after_edit = next(f for f in desktop.request.get(URL + '/api/state').json()['frames'] if f['id'] == first['id'])
                        if after_edit['edit']['rotation'] == 90:
                            break
                        time.sleep(.05)
                    assert after_edit['sha256'] == first['sha256']
                    assert after_edit['edit']['rotation'] == 90
                    assert after_edit['edit']['film_base'] == [.95, .9, .85]
                    with page.expect_download() as downloaded:
                        page.get_by_role('link', name='EXPORT TIFF ↗', exact=True).click()
                    assert downloaded.value.suggested_filename.endswith('.tiff')
                    with tifffile.TiffFile(downloaded.value.path()) as output:
                        assert output.pages[0].bitspersample == 16
                    page.get_by_role('button', name='Archive ↗', exact=True).click()
                    expect(page.locator('.roll-detail')).to_contain_text('archived')
                    page.reload()
                    mobile.reload()
                    page.wait_for_selector('main')
                    mobile.wait_for_selector('main')
                    page.wait_for_timeout(600)
                    assert mobile.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                    page.evaluate('window.scrollTo(0, 0)')
                    mobile.evaluate('window.scrollTo(0, 0)')
                    page.screenshot(path=str(evidence / 'desktop-home.png'), full_page=True)
                    mobile.screenshot(path=str(evidence / 'iphone-home.png'), full_page=True)
                    assert not errors, errors
                    report = {'result': 'passed', 'frames': 36, 'development': 'real elapsed rehearsal with reload',
                              'scan_workspace': 'prescan strip 36, film profile, dragged window 20-80%, exposure R 105%; settings on every saved frame',
                              'phone': '390x844 Chromium emulation; completed preview received during acquisition',
                              'reconnect': 'authenticated current snapshot', 'exports': '16-bit TIFF inspected',
                              'archive': 'integrity verified through UI', 'javascript_exceptions': errors,
                              'ui_controls': ['create roll', 'start developing', 'confirm transitions', 'connect', 'film profile', 'prescan', 'scan window drag', 'exposure', 'scan', 'shuffle', 'search stock/date', 'edit', 'TIFF download', 'archive']}
                    (ROOT / 'docs' / 'browser-validation.json').write_text(json.dumps(report, indent=2), encoding='utf8')
                    print(json.dumps(report))
                    browser.close()
            finally:
                service.terminate()
                try:
                    service.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    service.kill()
                    service.wait()


if __name__ == '__main__':
    run()
