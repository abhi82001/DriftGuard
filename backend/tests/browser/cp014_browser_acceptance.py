"""Real Chromium CP014 workflow acceptance. Run explicitly; launches uvicorn."""
from pathlib import Path
import os, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[3]
SHOT=ROOT/'artifacts'/'cp014-screenshots'; SHOT.mkdir(parents=True,exist_ok=True)
PORT=8765; BASE=f'http://127.0.0.1:{PORT}'

def wait_server():
    for _ in range(80):
        try:
            urllib.request.urlopen(BASE,timeout=.2); return
        except Exception: time.sleep(.1)
    raise RuntimeError('server did not start')

def test_real_browser_end_to_end(tmp_path):
    env=os.environ.copy(); env['DRIFTGUARD_DEMO_MODE']='1'; env['PYTHONPATH']='backend/src'
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','backend.src.app:app','--host','127.0.0.1','--port',str(PORT)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        wait_server()
        policy=tmp_path/'Access_Policy.txt'; policy.write_text('Information Security Policy. MFA is required for all workforce access to production systems.')
        backup=tmp_path/'Backup_Job_Report.csv'; backup.write_text('system,frequency,date,result\\nprod-db,Daily,2026-09-29,Success\\nprod-db,Daily,2026-09-30,Failed\\n')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
            page=browser.new_page()
            try:
                page.goto(BASE)
                page.fill('#vendor','Browser Acceptance Vendor')
                page.set_input_files('#files',[str(policy),str(backup)])
                page.click('button:has-text("Analyze Documents")')
                page.wait_for_url('**/doc-results/**')
                assert page.get_by_text('Assessment overview').is_visible()
                assert page.get_by_text('SEMANTIC ANALYSIS UNAVAILABLE').is_visible()
                assert page.get_by_text('Questions evaluated').is_visible()
                # provenance/details exist on the actual result surface
                assert page.locator('text=Evidence rejected:').first.is_visible()
                # Evidence QA navigation
                page.get_by_text('Open the Evidence QA report').click()
                page.wait_for_url('**/evidence-report/**')
                assert page.get_by_text('Recognized artifact type:').first.is_visible()
                assert page.get_by_text('Validator used:').first.is_visible()
                page.get_by_text('Back to document analysis').click(); page.wait_for_url('**/doc-results/**')
                # Clarification -> reassessment/manual result
                form=page.locator('form[action^="/clarify/"]')
                if form.count():
                    sel=form.locator('select').first
                    if sel.count(): sel.select_option(index=1)
                    else:
                        ta=form.locator('textarea').first
                        if ta.count(): ta.fill('Reviewer clarification supplied from browser acceptance test.')
                    form.locator('button').click(); page.wait_for_url('**/results/**')
                    assert page.get_by_text('Results').first.is_visible()
                # Return to document assessment to test export.
                page.goto(BASE)
                page.fill('#vendor','Export Vendor'); page.set_input_files('#files',str(policy)); page.click('button:has-text("Analyze Documents")'); page.wait_for_url('**/doc-results/**')
                with page.expect_download() as dl:
                    page.get_by_text('Export JSON report').click()
                assert dl.value.suggested_filename.startswith('driftguard-')
            except Exception:
                page.screenshot(path=str(SHOT/'workflow-failure.png'),full_page=True)
                raise
            finally: browser.close()
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
