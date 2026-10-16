from pathlib import Path
import shutil
import sys
import yaml

REPO = Path(__file__).resolve().parents[2]
ROOT = Path(r'D:\Jarvis-v2-dev\portfolio-video-20261012')
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from scripts.bootstrap import create_tree
from app.config.loader import load_config

create_tree(ROOT)
source = Path(r'D:\Jarvis-v2-dev\config')
settings = yaml.safe_load((source / 'settings.yaml').read_text(encoding='utf-8'))
settings['paths']['data_root'] = str(ROOT)
settings['voice']['enabled'] = False
settings['command_memory']['enabled'] = False
settings['memory']['summarize_on_exit'] = False
settings['session']['recovery'] = 'discard'
settings['llm']['max_output_tokens'] = 500
(ROOT / 'config/settings.yaml').write_text(yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding='utf-8')
for name in ['tools.yaml', 'privacy.yaml']:
    shutil.copyfile(source / name, ROOT / 'config' / name)
tools = yaml.safe_load((ROOT / 'config/tools.yaml').read_text(encoding='utf-8'))
for tool in tools['tools']:
    if tool['name'] in {'web_search', 'fetch_url'}:
        tool['enabled'] = False
(ROOT / 'config/tools.yaml').write_text(yaml.safe_dump(tools, allow_unicode=True, sort_keys=False), encoding='utf-8')
(ROOT / 'docs/Jarvis_소개.txt').write_text('''Jarvis 프로젝트 소개 — 촬영용 샘플 문서

Jarvis는 Windows에서 실행하는 개인 AI 비서다.
Python과 Ollama를 사용하며, 로컬 문서를 검색하고 자연어로 프로그램을 실행한다.
문서 검색은 SQLite FTS5(BM25), 특징 해싱 기반 벡터 검색, RRF 순위 결합을 사용한다.
프로그램 실행 전에는 도구 정책과 실행 권한을 확인한다.
''', encoding='utf-8')
load_config(ROOT / 'config')
print(f'Recording configuration ready: {ROOT / "config"}')
