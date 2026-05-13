#!/usr/bin/env python3
"""
同步 openclaw.json 中的 agent 配置 → data/agent_config.json
支持自動發現 agent workspace 下的 Skills 目錄
"""
import json, os, pathlib, datetime, logging
from file_lock import atomic_json_write
from utils import get_openclaw_home

log = logging.getLogger('sync_agent_config')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

# Auto-detect project root (parent of scripts/)
BASE = pathlib.Path(__file__).parent.parent
DATA = BASE / 'data'
OPENCLAW_HOME = get_openclaw_home()
OPENCLAW_CFG = OPENCLAW_HOME / 'openclaw.json'

ID_LABEL = {
    'taizi':    {'label': '太子',   'role': '太子',     'duty': '飛書消息分揀與回奏',  'emoji': '🤴'},
    'main':     {'label': '太子',   'role': '太子',     'duty': '飛書消息分揀與回奏',  'emoji': '🤴'},  # 兼容舊配置
    'zhongshu': {'label': '中書省', 'role': '中書令',   'duty': '起草任務令與優先級',  'emoji': '📜'},
    'menxia':   {'label': '門下省', 'role': '侍中',     'duty': '審議與退回機制',      'emoji': '🔍'},
    'shangshu': {'label': '尚書省', 'role': '尚書令',   'duty': '派單與升級裁決',      'emoji': '📮'},
    'libu':     {'label': '禮部',   'role': '禮部尚書', 'duty': '文檔/匯報/規範',      'emoji': '📝'},
    'hubu':     {'label': '戶部',   'role': '戶部尚書', 'duty': '資源/預算/成本',      'emoji': '💰'},
    'bingbu':   {'label': '兵部',   'role': '兵部尚書', 'duty': '工程實現與架構設計',  'emoji': '⚔️'},
    'xingbu':   {'label': '刑部',   'role': '刑部尚書', 'duty': '合規/審計/紅線',      'emoji': '⚖️'},
    'gongbu':   {'label': '工部',   'role': '工部尚書', 'duty': '基礎設施與部署運維',  'emoji': '🔧'},
    'libu_hr':  {'label': '吏部',   'role': '吏部尚書', 'duty': '人事/培訓/Agent管理',  'emoji': '👔'},
    'zaochao':  {'label': '欽天監', 'role': '朝報官',   'duty': '每日新聞採集與簡報',  'emoji': '📰'},
}

KNOWN_MODELS = [
    {'id': 'anthropic/claude-sonnet-4-6', 'label': 'Claude Sonnet 4.6', 'provider': 'Anthropic'},
    {'id': 'anthropic/claude-opus-4-5',   'label': 'Claude Opus 4.5',   'provider': 'Anthropic'},
    {'id': 'anthropic/claude-haiku-3-5',  'label': 'Claude Haiku 3.5',  'provider': 'Anthropic'},
    {'id': 'openai/gpt-4o',               'label': 'GPT-4o',            'provider': 'OpenAI'},
    {'id': 'openai/gpt-4o-mini',          'label': 'GPT-4o Mini',       'provider': 'OpenAI'},
    {'id': 'openai-codex/gpt-5.3-codex',  'label': 'GPT-5.3 Codex',    'provider': 'OpenAI Codex'},
    {'id': 'google/gemini-2.0-flash',     'label': 'Gemini 2.0 Flash',  'provider': 'Google'},
    {'id': 'google/gemini-2.5-pro',       'label': 'Gemini 2.5 Pro',    'provider': 'Google'},
    {'id': 'copilot/claude-sonnet-4',     'label': 'Claude Sonnet 4',   'provider': 'Copilot'},
    {'id': 'copilot/claude-opus-4.5',     'label': 'Claude Opus 4.5',   'provider': 'Copilot'},
    {'id': 'github-copilot/claude-opus-4.6', 'label': 'Claude Opus 4.6', 'provider': 'GitHub Copilot'},
    {'id': 'copilot/gpt-4o',              'label': 'GPT-4o',            'provider': 'Copilot'},
    {'id': 'copilot/gemini-2.5-pro',      'label': 'Gemini 2.5 Pro',    'provider': 'Copilot'},
    {'id': 'copilot/o3-mini',             'label': 'o3-mini',           'provider': 'Copilot'},
]


def normalize_model(model_value, fallback='unknown'):
    if isinstance(model_value, str) and model_value:
        return model_value
    if isinstance(model_value, dict):
        return model_value.get('primary') or model_value.get('id') or fallback
    return fallback


def get_skills(workspace: str):
    skills_dir = pathlib.Path(workspace) / 'skills'
    skills = []
    try:
        if skills_dir.exists():
            for d in sorted(skills_dir.iterdir()):
                if d.is_dir():
                    md = d / 'SKILL.md'
                    desc = ''
                    if md.exists():
                        try:
                            for line in md.read_text(encoding='utf-8', errors='ignore').splitlines():
                                line = line.strip()
                                if line and not line.startswith('#') and not line.startswith('---'):
                                    desc = line[:100]
                                    break
                        except Exception:
                            desc = '(讀取失敗)'
                    skills.append({'name': d.name, 'path': str(md), 'exists': md.exists(), 'description': desc})
    except PermissionError as e:
        log.warning(f'Skills 目錄訪問受限: {e}')
    return skills


def _collect_openclaw_models(cfg):
    """從 openclaw.json 中收集所有已配置的 model id，與 KNOWN_MODELS 合併去重。
    解決 #127: 自定義 provider 的 model 不在下拉列表中。
    """
    known_ids = {m['id'] for m in KNOWN_MODELS}
    extra = []
    agents_cfg = cfg.get('agents', {})
    # 收集 defaults.model
    dm = normalize_model(agents_cfg.get('defaults', {}).get('model', {}), '')
    if dm and dm not in known_ids:
        extra.append({'id': dm, 'label': dm, 'provider': 'OpenClaw'})
        known_ids.add(dm)
    # 收集 defaults.models 中的所有模型（OpenClaw 默認啓用的模型列表）
    defaults_models = agents_cfg.get('defaults', {}).get('models', {})
    if isinstance(defaults_models, dict):
        for model_id in defaults_models.keys():
            if model_id and model_id not in known_ids:
                provider = 'OpenClaw'
                if '/' in model_id:
                    provider = model_id.split('/')[0]
                extra.append({'id': model_id, 'label': model_id, 'provider': provider})
                known_ids.add(model_id)
    # 收集每個 agent 的 model
    for ag in agents_cfg.get('list', []):
        m = normalize_model(ag.get('model', ''), '')
        if m and m not in known_ids:
            extra.append({'id': m, 'label': m, 'provider': 'OpenClaw'})
            known_ids.add(m)
    # 收集 providers 中的 model id（如 copilot-proxy、anthropic 等）
    for pname, pcfg in cfg.get('providers', {}).items():
        for mid in (pcfg.get('models') or []):
            mid_str = mid if isinstance(mid, str) else (mid.get('id') or mid.get('name') or '')
            if mid_str and mid_str not in known_ids:
                extra.append({'id': mid_str, 'label': mid_str, 'provider': pname})
                known_ids.add(mid_str)
    return KNOWN_MODELS + extra


def main():
    cfg = {}
    try:
        cfg = json.loads(OPENCLAW_CFG.read_text(encoding='utf-8'))
    except Exception as e:
        log.warning(f'cannot read openclaw.json: {e}')
        return

    agents_cfg = cfg.get('agents', {})
    default_model = normalize_model(agents_cfg.get('defaults', {}).get('model', {}), 'unknown')
    agents_list = agents_cfg.get('list', [])
    merged_models = _collect_openclaw_models(cfg)

    result = []
    seen_ids = set()
    for ag in agents_list:
        ag_id = ag.get('id', '')
        if ag_id not in ID_LABEL:
            continue
        meta = ID_LABEL[ag_id]
        workspace = ag.get('workspace', str(OPENCLAW_HOME / f'workspace-{ag_id}'))
        if 'allowAgents' in ag:
            allow_agents = ag.get('allowAgents', []) or []
        else:
            allow_agents = ag.get('subagents', {}).get('allowAgents', [])
        result.append({
            'id': ag_id,
            'label': meta['label'], 'role': meta['role'], 'duty': meta['duty'], 'emoji': meta['emoji'],
            'model': normalize_model(ag.get('model', default_model), default_model),
            'defaultModel': default_model,
            'workspace': workspace,
            'skills': get_skills(workspace),
            'allowAgents': allow_agents,
        })
        seen_ids.add(ag_id)

    # 補充不在 openclaw.json agents list 中的 agent（兼容舊版 main）
    EXTRA_AGENTS = {
        'taizi':   {'model': default_model, 'workspace': str(OPENCLAW_HOME / 'workspace-taizi'),
                    'allowAgents': ['zhongshu']},
        'main':    {'model': default_model, 'workspace': str(OPENCLAW_HOME / 'workspace-main'),
                    'allowAgents': ['zhongshu','menxia','shangshu','hubu','libu','bingbu','xingbu','gongbu','libu_hr']},
        'zaochao': {'model': default_model, 'workspace': str(OPENCLAW_HOME / 'workspace-zaochao'),
                    'allowAgents': []},
        'libu_hr': {'model': default_model, 'workspace': str(OPENCLAW_HOME / 'workspace-libu_hr'),
                    'allowAgents': ['shangshu']},
    }
    for ag_id, extra in EXTRA_AGENTS.items():
        if ag_id in seen_ids or ag_id not in ID_LABEL:
            continue
        meta = ID_LABEL[ag_id]
        result.append({
            'id': ag_id,
            'label': meta['label'], 'role': meta['role'], 'duty': meta['duty'], 'emoji': meta['emoji'],
            'model': extra['model'],
            'defaultModel': default_model,
            'workspace': extra['workspace'],
            'skills': get_skills(extra['workspace']),
            'allowAgents': extra['allowAgents'],
            'isDefaultModel': True,
        })

    # 保留已有的 dispatchChannel 配置 (Fix #139)
    existing_cfg = {}
    cfg_path = DATA / 'agent_config.json'
    if cfg_path.exists():
        try:
            existing_cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        except Exception:
            pass

    payload = {
        'generatedAt': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'defaultModel': default_model,
        'knownModels': merged_models,
        'dispatchChannel': existing_cfg.get('dispatchChannel') or os.getenv('DEFAULT_DISPATCH_CHANNEL', ''),
        'agents': result,
    }
    DATA.mkdir(exist_ok=True)
    atomic_json_write(DATA / 'agent_config.json', payload)
    log.info(f'{len(result)} agents synced')

    # 自動部署 SOUL.md 到 workspace（如果項目裏有更新）
    deploy_soul_files()
    # 同步 scripts/ 到各 workspace（保持 kanban_update.py 等最新）
    sync_scripts_to_workspaces()


# 項目 agents/ 目錄名 → 運行時 agent_id 映射
_SOUL_DEPLOY_MAP = {
    'taizi': 'taizi',
    'zhongshu': 'zhongshu',
    'menxia': 'menxia',
    'shangshu': 'shangshu',
    'libu': 'libu',
    'hubu': 'hubu',
    'bingbu': 'bingbu',
    'xingbu': 'xingbu',
    'gongbu': 'gongbu',
    'libu_hr': 'libu_hr',
    'zaochao': 'zaochao',
}

def _sync_script_symlink(src_file: pathlib.Path, dst_file: pathlib.Path) -> bool:
    """Create a symlink dst_file → src_file (resolved).

    Using symlinks instead of physical copies ensures that ``__file__`` in
    each script always resolves back to the project ``scripts/`` directory,
    so relative-path computations like ``Path(__file__).resolve().parent.parent``
    point to the correct project root regardless of which workspace runs the
    script.  (Fixes #56 — kanban data-path split)

    Returns True if the link was (re-)created, False if already up-to-date.
    """
    src_resolved = src_file.resolve()
    # Guard: skip if dst resolves to the same real path as src.
    # This happens when ws_scripts is itself a directory-level symlink pointing
    # to the project scripts/ dir (created by install.sh link_resources).
    # Without this check the function would unlink the real source file and
    # then create a self-referential symlink (foo.py -> foo.py).
    try:
        dst_resolved = dst_file.resolve()
    except OSError:
        dst_resolved = None
    if dst_resolved == src_resolved:
        return False
    # Already a correct symlink?
    if dst_file.is_symlink() and dst_resolved == src_resolved:
        return False
    # Remove stale file / old physical copy / broken symlink
    if dst_file.exists() or dst_file.is_symlink():
        dst_file.unlink()
    os.symlink(src_resolved, dst_file)
    return True


def sync_scripts_to_workspaces():
    """將項目 scripts/ 目錄同步到各 agent workspace（保持 kanban_update.py 等最新）

    Uses symlinks so that ``__file__`` in workspace copies resolves to the
    project ``scripts/`` directory, keeping path-derived constants like
    ``TASKS_FILE`` pointing to the canonical ``data/`` folder.
    """
    scripts_src = BASE / 'scripts'
    if not scripts_src.is_dir():
        return
    home = get_openclaw_home()
    synced = 0
    for proj_name, runtime_id in _SOUL_DEPLOY_MAP.items():
        ws_scripts = home / f'workspace-{runtime_id}' / 'scripts'
        ws_scripts.mkdir(parents=True, exist_ok=True)
        for src_file in scripts_src.iterdir():
            if src_file.suffix not in ('.py', '.sh') or src_file.stem.startswith('__'):
                continue
            dst_file = ws_scripts / src_file.name
            try:
                if _sync_script_symlink(src_file, dst_file):
                    synced += 1
            except Exception:
                continue
    # also sync to workspace-main for legacy compatibility
    ws_main_scripts = home / 'workspace-main' / 'scripts'
    ws_main_scripts.mkdir(parents=True, exist_ok=True)
    for src_file in scripts_src.iterdir():
        if src_file.suffix not in ('.py', '.sh') or src_file.stem.startswith('__'):
            continue
        dst_file = ws_main_scripts / src_file.name
        try:
            if _sync_script_symlink(src_file, dst_file):
                synced += 1
        except Exception:
            pass
    if synced:
        log.info(f'{synced} script symlinks synced to workspaces')


def deploy_soul_files():
    """將項目 agents/xxx/SOUL.md 部署到 ~/.openclaw/workspace-xxx/SOUL.md"""
    agents_dir = BASE / 'agents'
    home = get_openclaw_home()
    deployed = 0
    for proj_name, runtime_id in _SOUL_DEPLOY_MAP.items():
        src = agents_dir / proj_name / 'SOUL.md'
        if not src.exists():
            continue
        ws_dst = home / f'workspace-{runtime_id}' / 'SOUL.md'
        ws_dst.parent.mkdir(parents=True, exist_ok=True)
        # 只在內容不同時更新（避免不必要的寫入）
        src_text = src.read_text(encoding='utf-8', errors='ignore')
        try:
            dst_text = ws_dst.read_text(encoding='utf-8', errors='ignore')
        except FileNotFoundError:
            dst_text = ''
        if src_text != dst_text:
            ws_dst.write_text(src_text, encoding='utf-8')
            deployed += 1
        # 太子兼容：同步一份到 legacy main agent 目錄
        if runtime_id == 'taizi':
            ag_dst = home / 'agents' / 'main' / 'SOUL.md'
            ag_dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                ag_text = ag_dst.read_text(encoding='utf-8', errors='ignore')
            except FileNotFoundError:
                ag_text = ''
            if src_text != ag_text:
                ag_dst.write_text(src_text, encoding='utf-8')
        # 確保 sessions 目錄存在
        sess_dir = home / 'agents' / runtime_id / 'sessions'
        sess_dir.mkdir(parents=True, exist_ok=True)
    if deployed:
        log.info(f'{deployed} SOUL.md files deployed')


if __name__ == '__main__':
    main()
