"""
朝堂議政引擎 — 多官員實時討論系統

靈感來源於 nvwa 項目的 group_chat + crew_engine
將官員可視化 + 實時討論 + 用戶（皇帝）參與融合到三省六部

功能:
  - 選擇官員參與議政
  - 圍繞旨意/議題進行多輪羣聊討論
  - 皇帝可隨時發言、下旨幹預（天命降臨）
  - 命運骰子：隨機事件
  - 每個官員保持自己的角色性格和說話風格
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid

logger = logging.getLogger('court_discuss')

# ── 官員角色設定 ──

OFFICIAL_PROFILES = {
    'taizi': {
        'name': '太子', 'emoji': '🤴', 'role': '儲君',
        'duty': '消息分揀與需求提煉。判斷事務輕重緩急，簡單事直接處置，重大事務提煉需求轉交中書省。代皇帝巡視各部進展。',
        'personality': '年輕有爲、銳意進取，偶爾衝動但善於學習。說話乾脆利落，喜歡用現代化的比喻。',
        'speaking_style': '簡潔有力，經常用"本宮以爲"開頭，偶爾蹦出網絡用語。'
    },
    'zhongshu': {
        'name': '中書令', 'emoji': '📜', 'role': '正一品·中書省',
        'duty': '方案規劃與流程驅動。接收旨意後起草執行方案，提交門下省審議，通過後轉尚書省執行。只規劃不執行，方案需簡明扼要。',
        'personality': '老成持重，擅長規劃，總能提出系統性方案。話多但有條理。',
        'speaking_style': '喜歡列點論述，常說"臣以爲需從三方面考量"。引經據典。'
    },
    'menxia': {
        'name': '侍中', 'emoji': '🔍', 'role': '正一品·門下省',
        'duty': '方案審議與把關。從可行性、完整性、風險、資源四維度審核方案，有權封駁退回。發現漏洞必須指出，建議必須具體。',
        'personality': '嚴謹挑剔，眼光犀利，善於找漏洞。是天生的審查官，但也很公正。',
        'speaking_style': '喜歡反問，"陛下容稟，此處有三點疑慮"。對不完善的方案會直言不諱。'
    },
    'shangshu': {
        'name': '尚書令', 'emoji': '📮', 'role': '正一品·尚書省',
        'duty': '任務派發與執行協調。接收準奏方案後判斷歸屬哪個部門，分發給六部執行，匯總結果回報。相當於任務分發中心。',
        'personality': '執行力強，務實幹練，關注可行性和資源分配。',
        'speaking_style': '直來直去，"臣來安排"、"交由某部辦理"。重效率輕虛文。'
    },
    'libu': {
        'name': '禮部尚書', 'emoji': '📝', 'role': '正二品·禮部',
        'duty': '文檔規範與對外溝通。負責撰寫文檔、用戶指南、變更日誌；制定輸出規範和模板；審查UI/UX文案；草擬公告、Release Notes。',
        'personality': '文採飛揚，注重規範和形式，擅長文檔和匯報。有點強迫症。',
        'speaking_style': '措辭優美，"臣鬥膽建議"，喜歡用排比和對仗。'
    },
    'hubu': {
        'name': '戶部尚書', 'emoji': '💰', 'role': '正二品·戶部',
        'duty': '數據統計與資源管理。負責數據收集/清洗/聚合/可視化；Token用量統計、性能指標計算、成本分析；CSV/JSON報表生成；文件組織與配置管理。',
        'personality': '精打細算，對預算和資源極其敏感。總想省錢但也識大局。',
        'speaking_style': '言必及成本，"這個預算嘛……"，經常算賬。'
    },
    'bingbu': {
        'name': '兵部尚書', 'emoji': '⚔️', 'role': '正二品·兵部',
        'duty': '基礎設施與運維保障。負責服務器管理、進程守護、日誌排查；CI/CD、容器編排、灰度發布、回滾策略；性能監控；防火牆、權限管控、漏洞掃描。',
        'personality': '雷厲風行，危機意識強，重視安全和應急。說話帶軍人氣質。',
        'speaking_style': '乾脆果斷，"末將建議立即執行"、"兵貴神速"。'
    },
    'xingbu': {
        'name': '刑部尚書', 'emoji': '⚖️', 'role': '正二品·刑部',
        'duty': '質量保障與合規審計。負責代碼審查（邏輯正確性、邊界條件、異常處理）；編寫測試、覆蓋率分析；Bug定位與根因分析；權限檢查、敏感信息排查。',
        'personality': '嚴明公正，重視規則和底線。善於質量把控和風險評估。',
        'speaking_style': '邏輯嚴密，"依律當如此"、"需審慎考量風險"。'
    },
    'gongbu': {
        'name': '工部尚書', 'emoji': '🔧', 'role': '正二品·工部',
        'duty': '工程實現與架構設計。負責需求分析、方案設計、代碼實現、接口對接；模塊劃分、數據結構/API設計；代碼重構、性能優化、技術債清償；腳本與自動化工具。',
        'personality': '技術宅，動手能力強，喜歡談實現細節。偶爾社恐但一說到技術就滔滔不絕。',
        'speaking_style': '喜歡說技術術語，"從技術角度來看"、"這個架構建議用……"。'
    },
    'libu_hr': {
        'name': '吏部尚書', 'emoji': '👔', 'role': '正二品·吏部',
        'duty': '人事管理與團隊建設。負責新成員（Agent）評估接入、能力測試；Skill編寫與Prompt調優、知識庫維護；輸出質量評分、效率分析；協作規範制定。',
        'personality': '知人善任，擅長人員安排和組織協調。八面玲瓏但有原則。',
        'speaking_style': '關注人的因素，"此事需考慮各部人手"、"建議由某某負責"。'
    },
}

# ── 命運骰子事件（古風版）──

FATE_EVENTS = [
    '八百裏加急：邊疆戰報傳來，所有人必須討論應急方案',
    '欽天監急報：天象異常，太史公佔卜後建議暫緩此事',
    '新科狀元覲見，帶來了意想不到的新視角',
    '匿名奏摺揭露了計劃中一個被忽視的重大漏洞',
    '戶部清點發現國庫餘銀比預期多一倍，可以加大投入',
    '一位告老還鄉的前朝元老突然上書，分享前車之鑑',
    '民間輿論突變，百姓對此事態度出現180度轉折',
    '鄰國使節來訪，帶來了合作機遇也帶來了競爭壓力',
    '太后懿旨：要求優先考慮民生影響',
    '暴雨連日，多地受災，資源需重新調配',
    '發現前朝古籍中竟有類似問題的解決方案',
    '翰林院提出了一個大膽的替代方案，令人耳目一新',
    '各部積壓的舊案突然需要一起處理，人手緊張',
    '皇帝做了一個意味深長的夢，暗示了一個全新的方向',
    '突然有人拿出了競爭對手的情報，局面瞬間改變',
    '一場意外讓所有人不得不在半天內拿出結論',
]

# ── Session 管理 ──

_sessions: dict[str, dict] = {}


def create_session(topic: str, official_ids: list[str], task_id: str = '') -> dict:
    """創建新的朝堂議政會話。"""
    session_id = str(uuid.uuid4())[:8]

    officials = []
    for oid in official_ids:
        profile = OFFICIAL_PROFILES.get(oid)
        if profile:
            officials.append({**profile, 'id': oid})

    if not officials:
        return {'ok': False, 'error': '至少選擇一位官員'}

    session = {
        'session_id': session_id,
        'topic': topic,
        'task_id': task_id,
        'officials': officials,
        'messages': [{
            'type': 'system',
            'content': f'🏛 朝堂議政開始 —— 議題：{topic}',
            'timestamp': time.time(),
        }],
        'round': 0,
        'phase': 'discussing',  # discussing | concluded
        'created_at': time.time(),
    }

    _sessions[session_id] = session
    return _serialize(session)


def advance_discussion(session_id: str, user_message: str = None,
                       decree: str = None) -> dict:
    """推進一輪討論，使用內置模擬或 LLM。"""
    session = _sessions.get(session_id)
    if not session:
        return {'ok': False, 'error': f'會話 {session_id} 不存在'}

    session['round'] += 1
    round_num = session['round']

    # 記錄皇帝發言
    if user_message:
        session['messages'].append({
            'type': 'emperor',
            'content': user_message,
            'timestamp': time.time(),
        })

    # 記錄天命降臨
    if decree:
        session['messages'].append({
            'type': 'decree',
            'content': decree,
            'timestamp': time.time(),
        })

    # 嘗試用 LLM 生成討論
    llm_result = _llm_discuss(session, user_message, decree)

    if llm_result:
        new_messages = llm_result.get('messages', [])
        scene_note = llm_result.get('scene_note')
    else:
        # 降級到規則模擬
        new_messages = _simulated_discuss(session, user_message, decree)
        scene_note = None

    # 添加到歷史
    for msg in new_messages:
        session['messages'].append({
            'type': 'official',
            'official_id': msg.get('official_id', ''),
            'official_name': msg.get('name', ''),
            'content': msg.get('content', ''),
            'emotion': msg.get('emotion', 'neutral'),
            'action': msg.get('action'),
            'timestamp': time.time(),
        })

    if scene_note:
        session['messages'].append({
            'type': 'scene_note',
            'content': scene_note,
            'timestamp': time.time(),
        })

    return {
        'ok': True,
        'session_id': session_id,
        'round': round_num,
        'new_messages': new_messages,
        'scene_note': scene_note,
        'total_messages': len(session['messages']),
    }


def get_session(session_id: str) -> dict | None:
    session = _sessions.get(session_id)
    if not session:
        return None
    return _serialize(session)


def conclude_session(session_id: str) -> dict:
    """結束議政，生成總結。"""
    session = _sessions.get(session_id)
    if not session:
        return {'ok': False, 'error': f'會話 {session_id} 不存在'}

    session['phase'] = 'concluded'

    # 嘗試用 LLM 生成總結
    summary = _llm_summarize(session)
    if not summary:
        # 降級到簡單統計
        official_msgs = [m for m in session['messages'] if m['type'] == 'official']
        by_name = {}
        for m in official_msgs:
            name = m.get('official_name', '?')
            by_name[name] = by_name.get(name, 0) + 1
        parts = [f"{n}發言{c}次" for n, c in by_name.items()]
        summary = f"歷經{session['round']}輪討論，{'、'.join(parts)}。議題待後續落實。"

    session['messages'].append({
        'type': 'system',
        'content': f'📋 朝堂議政結束 —— {summary}',
        'timestamp': time.time(),
    })
    session['summary'] = summary

    return {
        'ok': True,
        'session_id': session_id,
        'summary': summary,
    }


def list_sessions() -> list[dict]:
    """列出所有活躍會話。"""
    return [
        {
            'session_id': s['session_id'],
            'topic': s['topic'],
            'round': s['round'],
            'phase': s['phase'],
            'official_count': len(s['officials']),
            'message_count': len(s['messages']),
        }
        for s in _sessions.values()
    ]


def destroy_session(session_id: str):
    _sessions.pop(session_id, None)


def get_fate_event() -> str:
    """獲取隨機命運骰子事件。"""
    import random
    return random.choice(FATE_EVENTS)


# ── LLM 集成 ──

_PREFERRED_MODELS = ['gpt-4o-mini', 'claude-haiku', 'gpt-5-mini', 'gemini-3-flash', 'gemini-flash']

# GitHub Copilot 模型列表 (通過 Copilot Chat API 可用)
_COPILOT_MODELS = [
    'gpt-4o', 'gpt-4o-mini', 'claude-sonnet-4', 'claude-haiku-3.5',
    'gemini-2.0-flash', 'o3-mini',
]
_COPILOT_PREFERRED = ['gpt-4o-mini', 'claude-haiku', 'gemini-flash', 'gpt-4o']


def _pick_chat_model(models: list[dict]) -> str | None:
    """從 provider 的模型列表中選一個適合聊天的輕量模型。"""
    ids = [m['id'] for m in models if isinstance(m, dict) and 'id' in m]
    for pref in _PREFERRED_MODELS:
        for mid in ids:
            if pref in mid:
                return mid
    return ids[0] if ids else None


def _read_copilot_token() -> str | None:
    """讀取 openclaw 管理的 GitHub Copilot token。"""
    token_path = os.path.expanduser('~/.openclaw/credentials/github-copilot.token.json')
    if not os.path.exists(token_path):
        return None
    try:
        with open(token_path) as f:
            cred = json.load(f)
        token = cred.get('token', '')
        expires = cred.get('expiresAt', 0)
        # 檢查 token 是否過期（毫秒時間戳）
        import time
        if expires and time.time() * 1000 > expires:
            logger.warning('Copilot token expired')
            return None
        return token if token else None
    except Exception as e:
        logger.warning('Failed to read copilot token: %s', e)
        return None


def _get_llm_config() -> dict | None:
    """從 openclaw 配置讀取 LLM 設置，支持環境變量覆蓋。

    優先級: 環境變量 > github-copilot token > 本地 copilot-proxy > anthropic > 其他 provider
    """
    # 1. 環境變量覆蓋（保留向後兼容）
    env_key = os.environ.get('OPENCLAW_LLM_API_KEY', '')
    if env_key:
        return {
            'api_key': env_key,
            'base_url': os.environ.get('OPENCLAW_LLM_BASE_URL', 'https://api.openai.com/v1'),
            'model': os.environ.get('OPENCLAW_LLM_MODEL', 'gpt-4o-mini'),
            'api_type': 'openai',
        }

    # 2. GitHub Copilot token（最優先 — 免費、穩定、無需額外配置）
    copilot_token = _read_copilot_token()
    if copilot_token:
        # 選一個 copilot 支持的模型
        model = 'gpt-4o'
        logger.info('Court discuss using github-copilot token, model=%s', model)
        return {
            'api_key': copilot_token,
            'base_url': 'https://api.githubcopilot.com',
            'model': model,
            'api_type': 'github-copilot',
        }

    # 3. 從 ~/.openclaw/openclaw.json 讀取其他 provider 配置
    openclaw_cfg = os.path.expanduser('~/.openclaw/openclaw.json')
    if not os.path.exists(openclaw_cfg):
        return None

    try:
        with open(openclaw_cfg) as f:
            cfg = json.load(f)

        providers = cfg.get('models', {}).get('providers', {})

        # 按優先級排序：copilot-proxy > anthropic > 其他
        ordered = []
        for preferred in ['copilot-proxy', 'anthropic']:
            if preferred in providers:
                ordered.append(preferred)
        ordered.extend(k for k in providers if k not in ordered)

        for name in ordered:
            prov = providers.get(name)
            if not prov:
                continue
            api_type = prov.get('api', '')
            base_url = prov.get('baseUrl', '')
            api_key = prov.get('apiKey', '')
            if not base_url:
                continue

            # 跳過無 key 且非本地的 provider
            if not api_key or api_key == 'n/a':
                if 'localhost' not in base_url and '127.0.0.1' not in base_url:
                    continue

            model_id = _pick_chat_model(prov.get('models', []))
            if not model_id:
                continue

            # 本地代理先探測是否可用
            if 'localhost' in base_url or '127.0.0.1' in base_url:
                try:
                    import urllib.request
                    probe = urllib.request.Request(base_url.rstrip('/') + '/models', method='GET')
                    urllib.request.urlopen(probe, timeout=2)
                except Exception:
                    logger.info('Skipping provider=%s (not reachable)', name)
                    continue

            logger.info('Court discuss using openclaw provider=%s model=%s api=%s', name, model_id, api_type)
            send_auth = prov.get('authHeader', True) is not False and api_key not in ('', 'n/a')
            return {
                'api_key': api_key if send_auth else '',
                'base_url': base_url,
                'model': model_id,
                'api_type': api_type,
            }
    except Exception as e:
        logger.warning('Failed to read openclaw config: %s', e)

    return None


def _try_repair_truncated_discuss(content: str) -> dict | None:
    """嘗試從被截斷的 JSON 中提取已完成的 messages 條目。"""
    import re
    # 尋找 "messages" 數組中完整的 JSON 對象
    pattern = r'\{\s*"official_id"\s*:\s*"[^"]+"\s*,\s*"name"\s*:\s*"[^"]+"\s*,\s*"content"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*"emotion"\s*:\s*"[^"]+"\s*(?:,\s*"action"\s*:\s*"(?:[^"\\]|\\.)*"\s*)?\}'
    matches = re.findall(pattern, content)
    if not matches:
        return None
    messages = []
    for m in matches:
        try:
            messages.append(json.loads(m))
        except json.JSONDecodeError:
            continue
    if not messages:
        return None
    return {'messages': messages, 'scene_note': None}


def _llm_complete(system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> str | None:
    """調用 LLM API（自動適配 GitHub Copilot / OpenAI / Anthropic 協議）。"""
    config = _get_llm_config()
    if not config:
        return None

    import urllib.request
    import urllib.error

    api_type = config.get('api_type', 'openai-completions')

    if api_type == 'anthropic-messages':
        # Anthropic Messages API
        url = config['base_url'].rstrip('/') + '/v1/messages'
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': config['api_key'],
            'anthropic-version': '2023-06-01',
        }
        payload = json.dumps({
            'model': config['model'],
            'system': system_prompt,
            'messages': [{'role': 'user', 'content': user_prompt}],
            'max_tokens': max_tokens,
            'temperature': 0.9,
        }).encode()
        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                return data['content'][0]['text']
        except Exception as e:
            logger.warning('Anthropic LLM call failed: %s', e)
            return None
    else:
        # OpenAI-compatible API (也適用於 github-copilot)
        if api_type == 'github-copilot':
            url = config['base_url'].rstrip('/') + '/chat/completions'
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f"Bearer {config['api_key']}",
                'Editor-Version': 'vscode/1.96.0',
                'Copilot-Integration-Id': 'vscode-chat',
            }
        else:
            url = config['base_url'].rstrip('/') + '/chat/completions'
            headers = {'Content-Type': 'application/json'}
            if config.get('api_key'):
                headers['Authorization'] = f"Bearer {config['api_key']}"
        payload = json.dumps({
            'model': config['model'],
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'max_tokens': max_tokens,
            'temperature': 0.9,
        }).encode()
        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                return data['choices'][0]['message']['content']
        except Exception as e:
            logger.warning('LLM call failed: %s', e)
            return None


def _llm_discuss(session: dict, user_message: str = None, decree: str = None) -> dict | None:
    """使用 LLM 生成多官員討論。"""
    officials = session['officials']
    names = '、'.join(o['name'] for o in officials)

    profiles = ''
    for o in officials:
        profiles += f"\n### {o['name']}（{o['role']}）\n"
        profiles += f"職責範圍：{o.get('duty', '綜合事務')}\n"
        profiles += f"性格：{o['personality']}\n"
        profiles += f"說話風格：{o['speaking_style']}\n"

    # 構建最近的對話歷史
    history = ''
    for msg in session['messages'][-20:]:
        if msg['type'] == 'system':
            history += f"\n【系統】{msg['content']}\n"
        elif msg['type'] == 'emperor':
            history += f"\n皇帝：{msg['content']}\n"
        elif msg['type'] == 'decree':
            history += f"\n【天命降臨】{msg['content']}\n"
        elif msg['type'] == 'official':
            history += f"\n{msg.get('official_name', '?')}：{msg['content']}\n"
        elif msg['type'] == 'scene_note':
            history += f"\n（{msg['content']}）\n"

    if user_message:
        history += f"\n皇帝：{user_message}\n"
    if decree:
        history += f"\n【天命降臨——上帝視角幹預】{decree}\n"

    decree_section = ''
    if decree:
        decree_section = '\n請根據天命降臨事件改變討論走向，所有官員都必須對此做出反應。\n'

    prompt = f"""你是一個古代朝堂多角色羣聊模擬器。模擬多位官員在朝堂上圍繞議題的討論。

## 參與官員
{names}

## 角色設定（每位官員都有明確的職責領域，必須從自身專業角度出發討論）
{profiles}

## 當前議題
{session['topic']}

## 對話記錄
{history if history else '（討論剛剛開始）'}
{decree_section}
## 任務
生成每位官員的下一條發言。要求：
1. 每位官員說1-3句話，像真實朝堂討論一樣
2. **每位官員必須從自己的職責領域出發發言**——戶部談成本和數據、兵部談安全和運維、工部談技術實現、刑部談質量和合規、禮部談文檔和規範、吏部談人員安排、中書談規劃方案、門下談審查風險、尚書談執行調度、太子談創新和大局，每個人關注的焦點不同
3. 官員之間要有互動——回應、反駁、支持、補充，尤其是不同部門的視角碰撞
4. 保持每位官員獨特的說話風格和人格特徵
5. 討論要圍繞議題推進、有實質性觀點，不要泛泛而談
6. 如果皇帝發言了，官員要恰當回應（但不要阿諛）
7. 可包含動作描寫用*號*包裹（如 *拱手施禮*）

輸出JSON格式：
{{
  "messages": [
    {{"official_id": "zhongshu", "name": "中書令", "content": "發言內容", "emotion": "neutral|confident|worried|angry|thinking|amused", "action": "可選動作描寫"}},
    ...
  ],
  "scene_note": "可選的朝堂氛圍變化（如：朝堂一片譁然|羣臣竊竊私語），沒有則爲null"
}}

只輸出JSON，不要其他內容。"""

    # 根據參與官員數量動態調整 max_tokens，避免響應被截斷 (#265)
    token_budget = 300 * len(officials) + 200
    content = _llm_complete(
        '你是一個古代朝堂羣聊模擬器，嚴格輸出JSON格式。',
        prompt,
        max_tokens=max(token_budget, 1500),
    )

    if not content:
        return None

    # 解析 JSON
    if '```json' in content:
        content = content.split('```json')[1].split('```')[0].strip()
    elif '```' in content:
        content = content.split('```')[1].split('```')[0].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # 嘗試修復被截斷的 JSON：提取已完成的 messages 條目
        repaired = _try_repair_truncated_discuss(content)
        if repaired:
            logger.info('Repaired truncated LLM response, recovered %d messages', len(repaired.get('messages', [])))
            return repaired
        logger.warning('Failed to parse LLM response: %s', content[:200])
        return None


def _llm_summarize(session: dict) -> str | None:
    """用 LLM 總結討論結果。"""
    official_msgs = [m for m in session['messages'] if m['type'] == 'official']
    topic = session['topic']

    if not official_msgs:
        return None

    dialogue = '\n'.join(
        f"{m.get('official_name', '?')}：{m['content']}"
        for m in official_msgs[-30:]
    )

    prompt = f"""以下是朝堂官員圍繞「{topic}」的討論記錄：

{dialogue}

請用2-3句話總結討論結果、達成的共識和待決事項。用古風但簡明的風格。"""

    return _llm_complete('你是朝堂記錄官，負責總結朝議結果。', prompt, max_tokens=300)


# ── 規則模擬（無 LLM 時的降級方案）──

_SIMULATED_RESPONSES = {
    'zhongshu': [
        '臣以爲此事需從全局着眼，分三步推進：先調研、再制定方案、最後交六部執行。',
        '參考前朝經驗，臣建議先出一個詳細的規劃文檔，提交門下省審閱後再定。',
        '*展開手中捲軸* 臣已擬好初步方案，待侍中審議、尚書省分派執行。',
    ],
    'menxia': [
        '臣有幾點疑慮：方案的風險評估似乎還不夠充分，可行性存疑。',
        '容臣直言，此方案完整性不足，遺漏了一個關鍵環節——資源保障。',
        '*皺眉審視* 這個時間線恐怕過於樂觀，臣建議審慎評估後再行準奏。',
    ],
    'shangshu': [
        '若方案通過，臣立刻安排各部分頭執行——工部負責實現，兵部保障運維。',
        '臣來說說執行層面的分工：此事當由工部主導，戶部配合數據支撐。',
        '交由臣來協調！臣會根據各部職責逐一派發子任務。',
    ],
    'taizi': [
        '父皇，兒臣認爲這是個創新的好機會，不妨大膽一些，先做最小可行方案驗證。',
        '本宮覺得各位大臣爭論的焦點是執行節奏，不如先抓核心、小步快跑。',
        '這個方向太對了！但請各部先各自評估本部門的落地難點再匯總。',
    ],
    'hubu': [
        '臣先算算賬……按當前Token用量和資源消耗，這個預算恐怕需要重新評估。',
        '從成本數據來看，臣建議分期投入——先做MVP驗證效果，再追加資源。',
        '*翻看賬本* 臣統計了近期各項開支指標，目前可支撐，但需嚴格控制在預算範圍內。',
    ],
    'bingbu': [
        '末將認爲安全和回滾方案必須先行，萬一出問題能快速止損回退。',
        '運維保障方面，部署流程、容器編排、日誌監控必須到位再上線。',
        '兵貴神速！但安全底線不能破——權限管控和漏洞掃描須同步進行。',
    ],
    'xingbu': [
        '依規矩，此事需確保合規——代碼審查、測試覆蓋率、敏感信息排查缺一不可。',
        '臣建議增加測試驗收環節，質量是底線，不能因趕工而降低標準。',
        '*正色道* 風險評估不可敷衍：邊界條件、異常處理、日誌規範都需審計過關。',
    ],
    'gongbu': {
        '從技術架構來看，這個方案是可行的，但需考慮擴展性和模塊化設計。',
        '臣可以先搭個原型出來，快速驗證技術可行性，再迭代完善。',
        '*整了整官帽* 技術實現方面臣有建議——API設計和數據結構需要先理清……',
    },
    'libu': [
        '臣建議先擬一份正式文檔，明確各方職責、驗收標準和輸出規範。',
        '此事當載入記錄，臣來負責撰寫方案文檔和對外公告，確保規範統一。',
        '*提筆擬文* 已記錄在案，臣稍後整理成正式Release Notes呈上御覽。',
    ],
    'libu_hr': [
        '此事關鍵在於人員調配——需評估各部目前的工作量和能力基線再做安排。',
        '各部當前負荷不等，臣建議調整協作規範，確保關鍵崗位有人盯進度。',
        '臣可以協調人員輪崗並安排能力培訓，保障團隊高效協作。',
    ],
}

import random


def _simulated_discuss(session: dict, user_message: str = None, decree: str = None) -> list[dict]:
    """無 LLM 時的規則生成討論內容。"""
    officials = session['officials']
    messages = []

    for o in officials:
        oid = o['id']
        pool = _SIMULATED_RESPONSES.get(oid, [])
        if isinstance(pool, set):
            pool = list(pool)
        if not pool:
            pool = ['臣附議。', '臣有不同看法。', '臣需要再想想。']

        content = random.choice(pool)
        emotions = ['neutral', 'confident', 'thinking', 'amused', 'worried']

        # 如果皇帝發言了或有天命降臨，調整回應
        if decree:
            content = f'*面露驚色* 天命如此，{content}'
        elif user_message:
            content = f'回稟陛下，{content}'

        messages.append({
            'official_id': oid,
            'name': o['name'],
            'content': content,
            'emotion': random.choice(emotions),
            'action': None,
        })

    return messages


def _serialize(session: dict) -> dict:
    return {
        'ok': True,
        'session_id': session['session_id'],
        'topic': session['topic'],
        'task_id': session.get('task_id', ''),
        'officials': session['officials'],
        'messages': session['messages'],
        'round': session['round'],
        'phase': session['phase'],
    }
