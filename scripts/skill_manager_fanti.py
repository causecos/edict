#!/usr/bin/env python3
"""
三省六部 · Skill 管理工具
支持從本地或遠程 URL 添加、更新、查看和移除 skills

Usage:
  python3 scripts/skill_manager.py add-remote --agent zhongshu --name code_review \\
    --source https://raw.githubusercontent.com/org/skills/main/code_review/SKILL.md \\
    --description "代碼審查"
  
  python3 scripts/skill_manager.py list-remote
  
  python3 scripts/skill_manager.py update-remote --agent zhongshu --name code_review
  
  python3 scripts/skill_manager.py remove-remote --agent zhongshu --name code_review
  
  python3 scripts/skill_manager.py import-official-hub --agents zhongshu,menxia,shangshu
"""
import sys
import json
import pathlib
import argparse
import os
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_openclaw_home, now_iso, safe_name, read_json

OCLAW_HOME = get_openclaw_home()


def _download_file(url: str, timeout: int = 30, retries: int = 3) -> str:
    """從 URL 下載文件內容（文本格式），支持重試"""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'OpenClaw-SkillManager/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read(10 * 1024 * 1024)  # 最多 10MB
                return content.decode('utf-8')
        except urllib.error.HTTPError as e:
            last_error = f'HTTP {e.code}: {e.reason}'
            if e.code in (404, 403):
                break  # 不重試 4xx
        except urllib.error.URLError as e:
            last_error = f'網絡錯誤: {e.reason}'
        except Exception as e:
            last_error = f'{type(e).__name__}: {e}'
        
        if attempt < retries:
            import time
            wait = attempt * 3  # 3s, 6s
            print(f'   ⚠️ 第 {attempt} 次下載失敗({last_error})，{wait}秒後重試...')
            time.sleep(wait)
    
    # 所有重試失敗
    hint = ''
    if 'timed out' in str(last_error).lower() or '超時' in str(last_error):
        hint = '\n   💡 提示: 如果在中國大陸，請設置代理 export https_proxy=http://proxy:port'
    elif '404' in str(last_error):
        hint = '\n   💡 提示: 官方 Skills Hub 可能尚未發布該 skill，請檢查 URL 是否正確'
    raise Exception(f'{last_error} (已重試 {retries} 次){hint}')


def _compute_checksum(content: str) -> str:
    """計算內容的簡單校驗和"""
    import hashlib
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def add_remote(agent_id: str, name: str, source_url: str, description: str = '') -> bool:
    """從遠程 URL 爲 Agent 添加 skill"""
    if not safe_name(agent_id) or not safe_name(name):
        print(f'❌ 錯誤：agent_id 或 skill 名稱含非法字符')
        return False
    
    # 設置 workspace
    workspace = OCLAW_HOME / f'workspace-{agent_id}' / 'skills' / name
    workspace.mkdir(parents=True, exist_ok=True)
    skill_md = workspace / 'SKILL.md'
    
    # 下載文件
    print(f'⏳ 正在從 {source_url} 下載...')
    try:
        content = _download_file(source_url)
    except Exception as e:
        print(f'❌ 下載失敗：{e}')
        print(f'   URL: {source_url}')
        return False
    
    # 基礎驗證（放寬檢查：有些 skill 不以 --- 開頭）
    if len(content.strip()) < 10:
        print(f'❌ 文件內容過短或爲空')
        return False
    
    # 保存 SKILL.md
    skill_md.write_text(content)
    
    # 保存源信息
    source_info = {
        'skillName': name,
        'sourceUrl': source_url,
        'description': description,
        'addedAt': now_iso(),
        'lastUpdated': now_iso(),
        'checksum': _compute_checksum(content),
        'status': 'valid',
    }
    source_json = workspace / '.source.json'
    source_json.write_text(json.dumps(source_info, ensure_ascii=False, indent=2))
    
    print(f'✅ 技能 {name} 已添加到 {agent_id}')
    print(f'   路徑: {skill_md}')
    print(f'   大小: {len(content)} 字節')
    return True


def list_remote() -> bool:
    """列出所有已添加的遠程 skills"""
    if not OCLAW_HOME.exists():
        print('❌ OCLAW_HOME 不存在')
        return False
    
    remote_skills = []
    
    for ws_dir in OCLAW_HOME.glob('workspace-*'):
        agent_id = ws_dir.name.replace('workspace-', '')
        skills_dir = ws_dir / 'skills'
        if not skills_dir.exists():
            continue
        
        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_name = skill_dir.name
            source_json = skill_dir / '.source.json'
            
            if not source_json.exists():
                continue
            
            try:
                source_info = json.loads(source_json.read_text())
                remote_skills.append({
                    'agent': agent_id,
                    'skill': skill_name,
                    'source': source_info.get('sourceUrl', 'N/A'),
                    'desc': source_info.get('description', ''),
                    'added': source_info.get('addedAt', 'N/A'),
                })
            except Exception:
                pass
    
    if not remote_skills:
        print('📭 暫無遠程 skills')
        return True
    
    print(f'📋 共 {len(remote_skills)} 個遠程 skills：\n')
    print(f'{"Agent":<12} | {"Skill 名稱":<20} | {"描述":<30} | 添加時間')
    print('-' * 100)
    
    for sk in remote_skills:
        desc = (sk['desc'] or sk['source'])[:30].ljust(30)
        print(f"{sk['agent']:<12} | {sk['skill']:<20} | {desc} | {sk['added'][:10]}")
    
    print()
    return True


def update_remote(agent_id: str, name: str) -> bool:
    """更新遠程 skill 爲最新版本"""
    if not safe_name(agent_id) or not safe_name(name):
        print(f'❌ 錯誤：agent_id 或 skill 名稱含非法字符')
        return False
    
    workspace = OCLAW_HOME / f'workspace-{agent_id}' / 'skills' / name
    source_json = workspace / '.source.json'
    
    if not source_json.exists():
        print(f'❌ 技能不存在或不是遠程 skill: {name}')
        return False
    
    try:
        source_info = json.loads(source_json.read_text())
        source_url = source_info.get('sourceUrl')
        if not source_url:
            print(f'❌ 無效的源 URL')
            return False
        
        # 重新下載
        return add_remote(agent_id, name, source_url, source_info.get('description', ''))
    except Exception as e:
        print(f'❌ 更新失敗：{e}')
        return False


def remove_remote(agent_id: str, name: str) -> bool:
    """移除遠程 skill"""
    if not safe_name(agent_id) or not safe_name(name):
        print(f'❌ 錯誤：agent_id 或 skill 名稱含非法字符')
        return False
    
    workspace = OCLAW_HOME / f'workspace-{agent_id}' / 'skills' / name
    source_json = workspace / '.source.json'
    
    if not source_json.exists():
        print(f'❌ 技能不存在或不是遠程 skill: {name}')
        return False
    
    try:
        import shutil
        shutil.rmtree(workspace)
        print(f'✅ 技能 {name} 已從 {agent_id} 移除')
        return True
    except Exception as e:
        print(f'❌ 移除失敗：{e}')
        return False


OFFICIAL_SKILLS_HUB_BASE = 'https://raw.githubusercontent.com/openclaw-ai/skills-hub/main'
# 備用鏡像（GitHub 國內訪問不穩定時自動切換）
_FALLBACK_HUB_BASES = [
    'https://ghproxy.com/https://raw.githubusercontent.com/openclaw-ai/skills-hub/main',
    'https://raw.gitmirror.com/openclaw-ai/skills-hub/main',
]

# 支持通過環境變量覆蓋 Hub 地址
_HUB_BASE_ENV = 'OPENCLAW_SKILLS_HUB_BASE'

def _get_hub_url(skill_name):
    """獲取 skill 的 Hub URL，支持環境變量覆蓋"""
    hub_url_file = OCLAW_HOME / 'skills-hub-url'
    base = hub_url_file.read_text().strip() if hub_url_file.exists() else None
    base = base or os.environ.get(_HUB_BASE_ENV) or OFFICIAL_SKILLS_HUB_BASE
    return f'{base.rstrip("/")}/{skill_name}/SKILL.md'


OFFICIAL_SKILLS_HUB = {
    'code_review': _get_hub_url('code_review'),
    'api_design': _get_hub_url('api_design'),
    'security_audit': _get_hub_url('security_audit'),
    'data_analysis': _get_hub_url('data_analysis'),
    'doc_generation': _get_hub_url('doc_generation'),
    'test_framework': _get_hub_url('test_framework'),
}

SKILL_AGENT_MAPPING = {
    'code_review': ('bingbu', 'xingbu', 'menxia'),
    'api_design': ('bingbu', 'gongbu', 'menxia'),
    'security_audit': ('xingbu', 'menxia'),
    'data_analysis': ('hubu', 'menxia'),
    'doc_generation': ('libu', 'menxia'),
    'test_framework': ('gongbu', 'xingbu', 'menxia'),
}


def import_official_hub(agent_ids: list) -> bool:
    """從官方 Skills Hub 導入指定的 skills 到指定 agents。
    如果未指定 agents，使用該 skill 的推薦 agents。
    """
    if not agent_ids:
        print('❌ 未指定 agent，使用推薦配置...\n')
        for skill_name, recommended_agents in SKILL_AGENT_MAPPING.items():
            agent_ids.extend(recommended_agents)
        agent_ids = list(set(agent_ids))
    
    total = 0
    success = 0
    failed = []
    
    for skill_name, url in OFFICIAL_SKILLS_HUB.items():
        # 確定目標 agents
        target_agents = agent_ids
        if not agent_ids:
            target_agents = SKILL_AGENT_MAPPING.get(skill_name, ['menxia'])
        
        print(f'\n📥 正在導入 skill: {skill_name}')
        print(f'   目標 agents: {", ".join(target_agents)}')
        
        # 嘗試主 URL，失敗則自動切換鏡像
        effective_url = url
        for agent_id in target_agents:
            total += 1
            ok = add_remote(agent_id, skill_name, effective_url, f'官方 skill：{skill_name}')
            if not ok and effective_url == url:
                # 主 URL 失敗，嘗試鏡像
                for fb_base in _FALLBACK_HUB_BASES:
                    fb_url = f'{fb_base.rstrip("/")}/{skill_name}/SKILL.md'
                    print(f'   🔄 嘗試鏡像: {fb_url}')
                    ok = add_remote(agent_id, skill_name, fb_url, f'官方 skill：{skill_name}')
                    if ok:
                        effective_url = fb_url  # 後續 agent 也用這個鏡像
                        break
            if ok:
                success += 1
            else:
                failed.append(f'{agent_id}/{skill_name}')
    
    print(f'\n📊 導入完成：{success}/{total} 個 skills 成功')
    if failed:
        print(f'\n❌ 失敗列表:')
        for f in failed:
            print(f'   - {f}')
        print(f'\n💡 排查建議:')
        print(f'   1. 檢查網絡: curl -I {OFFICIAL_SKILLS_HUB_BASE}/code_review/SKILL.md')
        print(f'   2. 設置代理: export https_proxy=http://your-proxy:port')
        print(f'   3. 使用鏡像: export {_HUB_BASE_ENV}=https://ghproxy.com/{OFFICIAL_SKILLS_HUB_BASE}')
        print(f'   4. 自定義源: echo "https://your-mirror/skills" > {OCLAW_HOME / "skills-hub-url"}')
        print(f'   5. 單獨重試: python3 scripts/skill_manager.py add-remote --agent <agent> --name <skill> --source <url>')
    return success == total


def main():
    parser = argparse.ArgumentParser(description='三省六部 Skill 管理工具', 
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest='cmd', help='命令')
    
    # add-remote
    add_parser = subparsers.add_parser('add-remote', help='從遠程 URL 添加 skill')
    add_parser.add_argument('--agent', required=True, help='目標 Agent ID')
    add_parser.add_argument('--name', required=True, help='Skill 內部名稱')
    add_parser.add_argument('--source', required=True, help='遠程 URL 或本地路徑')
    add_parser.add_argument('--description', default='', help='Skill 描述')
    
    # list-remote
    subparsers.add_parser('list-remote', help='列出所有遠程 skills')
    
    # update-remote
    update_parser = subparsers.add_parser('update-remote', help='更新遠程 skill')
    update_parser.add_argument('--agent', required=True, help='Agent ID')
    update_parser.add_argument('--name', required=True, help='Skill 名稱')
    
    # remove-remote
    remove_parser = subparsers.add_parser('remove-remote', help='移除遠程 skill')
    remove_parser.add_argument('--agent', required=True, help='Agent ID')
    remove_parser.add_argument('--name', required=True, help='Skill 名稱')
    
    # import-official-hub
    import_parser = subparsers.add_parser('import-official-hub', help='從官方庫導入 skills')
    import_parser.add_argument('--agents', default='', help='逗號分隔的 Agent IDs（可選）')
    
    # check-updates
    check_parser = subparsers.add_parser('check-updates', help='檢查更新（未來功能）')
    check_parser.add_argument('--interval', default='weekly', 
                             help='檢查間隔 (weekly/daily/monthly)')
    
    args = parser.parse_args()
    
    if not args.cmd:
        parser.print_help()
        return
    
    if args.cmd == 'add-remote':
        success = add_remote(args.agent, args.name, args.source, args.description)
        sys.exit(0 if success else 1)
    
    elif args.cmd == 'list-remote':
        success = list_remote()
        sys.exit(0 if success else 1)
    
    elif args.cmd == 'update-remote':
        success = update_remote(args.agent, args.name)
        sys.exit(0 if success else 1)
    
    elif args.cmd == 'remove-remote':
        success = remove_remote(args.agent, args.name)
        sys.exit(0 if success else 1)
    
    elif args.cmd == 'import-official-hub':
        agent_list = [a.strip() for a in args.agents.split(',') if a.strip()] if args.agents else []
        success = import_official_hub(agent_list)
        sys.exit(0 if success else 1)
    
    elif args.cmd == 'check-updates':
        print(f'⏳ 檢查更新功能（間隔: {args.interval}）尚未實現')
        print(f'   敬請期待...')


if __name__ == '__main__':
    main()
