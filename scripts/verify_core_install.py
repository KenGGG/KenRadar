"""Real fresh-core CLI/HTTP/worker smoke test against a separate synthetic DB."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', required=True)
    parser.add_argument('--name', default='fresh-core-install')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    executable = Path(args.python).resolve()
    if not executable.is_relative_to(repo) or not args.name.replace('-', '').isalnum():
        raise ValueError('Use a repository-local interpreter and a simple fixture name')
    root = repo / 'data/test-migration' / args.name
    root.mkdir(exist_ok=False)
    path = root/'config/config.yaml'
    path.parent.mkdir()
    path.write_text(yaml.safe_dump({'app':{'data_dir':str(root),'database_url':'sqlite:///'+(root/'db/fixture.sqlite3').as_posix()},'schedule':{'enabled':False,'source_radar_enabled':False},'ai':{'funasr':{'enabled':False,'managed':False},'whisper':{'enabled':False}},'notification':{'enabled':False},'publishing':{'github_pages':{'enabled':False},'github_sync':{'enabled':False,'auto_push':False}}}),encoding='utf-8')
    env = {key:value for key,value in os.environ.items() if key not in {'DATABASE_URL','KENRADAR_WEB_PASSWORD','AGNES_API_KEY','OPENAI_API_KEY','FEISHU_WEBHOOK_URL'}}
    def run(*arguments):
        return subprocess.run([str(executable),*arguments],cwd=repo,env=env,check=True,capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    optional = json.loads(run('-c',"import importlib.util,json,sqlite3; print(json.dumps({'sqlite':sqlite3.sqlite_version,'optional':{key:importlib.util.find_spec(key) is not None for key in ['psycopg','torch','funasr']}}))").stdout)
    run('-m','kenradar','--config',str(path),'migrate')
    run('-c',"import sys; from kenradar.core.config import load_config; from kenradar.storage import create_database; db=create_database(load_config(sys.argv[1])); cr=db.upsert_creator('douyin','fresh-fixture','全新环境合成样本',''); db.upsert_content_item('douyin','000000123456789',cr,title='全新环境国债样本'); db.enqueue_task_run('system_health_check',{},'fresh install health')",str(path))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port=listener.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    with (root/'web.log').open('w',encoding='utf-8') as logfile:
        process=subprocess.Popen([str(executable),'-m','kenradar','--config',str(path),'web','--host','127.0.0.1','--port',str(port)],cwd=repo,env=env,stdout=logfile,stderr=logfile,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            deadline=time.monotonic()+20
            while True:
                try:
                    with urllib.request.urlopen(base+'/health/ready',timeout=1) as response:
                        assert json.load(response)['ok']
                    break
                except Exception:
                    if process.poll() is not None or time.monotonic()>deadline:
                        raise RuntimeError('Fresh HTTP readiness failed; inspect the fixture log')
                    time.sleep(.1)
            with urllib.request.urlopen(base+'/api/content-items',timeout=5) as response:
                assert len(json.load(response)['items']) == 1
            with urllib.request.urlopen(base+'/api/settings',timeout=5) as response:
                assert len(json.load(response)['groups']) == 8
            run('-m','kenradar','--config',str(path),'worker','--once','--name','fresh-core-fixture')
            with urllib.request.urlopen(base+'/api/run-center?section=history',timeout=5) as response:
                history=json.load(response)
                assert history['items'][0]['status']=='success'
        finally:
            process.terminate()
            process.wait(10)
    report={**optional,'cli':True,'http_readiness':True,'file_database_content':True,'settings':True,'independent_worker':True,'external_actions':False,'production_switch':False}
    (root/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':
    main()
