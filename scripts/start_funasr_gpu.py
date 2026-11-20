"""Launch the repository GPU runtime from the existing managed startup hook.

The manager owns startup serialization and supplies model/endpoint/idle options.
This entry also works with a worker started before python_executable was added.
"""
import os
from pathlib import Path
import subprocess


def start():
    root = Path(__file__).resolve().parents[1]
    python = root / 'data/funasr-gpu-runtime/Scripts/python.exe'
    if not python.is_file():
        raise RuntimeError('The repository FunASR GPU environment is not installed')
    env = os.environ.copy()
    env['FUNASR_DEVICE'] = 'cuda:0'
    env['PYTHONUNBUFFERED'] = '1'
    runtime = Path(env.get('FUNASR_RUNTIME_DIR') or root / 'data')
    runtime.mkdir(parents=True, exist_ok=True)
    temporary = runtime / 'tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    env['TMP'] = env['TEMP'] = str(temporary)
    with (runtime / 'funasr_server.log').open('a', encoding='utf8') as log:
        process = subprocess.Popen([str(python), str(root / 'scripts/funasr_openai_server.py')],
                                   cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    (runtime / 'funasr_server.pid').write_text(str(process.pid), encoding='utf8')


if __name__ == '__main__':
    start()
