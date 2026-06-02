"""Agents API — Agent 配置和狀態查詢。"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter

log = logging.getLogger("edict.api.agents")
router = APIRouter()

# Agent 元信息（對應 agents/ 目錄下的 SOUL.md）
AGENT_META = {
    "zaochao": {"name": "早朝（朝會主持）", "role": "朝會召集與議程管理", "icon": "🏛️"},
    "taizi": {"name": "太子", "role": "任務分揀與派發", "icon": "👑"},
    "libu_hr": {"name": "吏部（人事）", "role": "人事與組織管理", "icon": "👤"},
    "shangshu": {"name": "尚書令", "role": "總協調與任務監督", "icon": "📜"},
    "zhongshu": {"name": "中書省", "role": "起草詔令與方案規劃", "icon": "✍️"},
    "menxia": {"name": "門下省", "role": "審核與封駁", "icon": "🔍"},
    "libu": {"name": "吏部", "role": "人事與組織管理", "icon": "👤"},
    "hubu": {"name": "戶部", "role": "財務與資源管理", "icon": "💰"},
    "gongbu": {"name": "工部", "role": "工程與技術實施", "icon": "🔧"},
    "xingbu": {"name": "刑部", "role": "規範與質量審查", "icon": "⚖️"},
    "bingbu": {"name": "兵部", "role": "安全與應急響應", "icon": "🛡️"},
}


@router.get("")
async def list_agents():
    """列出所有可用 Agent。"""
    agents = []
    for agent_id, meta in AGENT_META.items():
        agents.append({
            "id": agent_id,
            **meta,
        })
    return {"agents": agents}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """獲取 Agent 詳情。"""
    meta = AGENT_META.get(agent_id)
    if not meta:
        return {"error": f"Agent '{agent_id}' not found"}, 404

    # 嘗試讀取 SOUL.md
    soul_path = Path(__file__).parents[4] / "agents" / agent_id / "SOUL.md"
    soul_content = ""
    if soul_path.exists():
        soul_content = soul_path.read_text(encoding="utf-8")[:2000]

    return {
        "id": agent_id,
        **meta,
        "soul_preview": soul_content,
    }


@router.get("/{agent_id}/config")
async def get_agent_config(agent_id: str):
    """獲取 Agent 運行時配置。"""
    config_path = Path(__file__).parents[4] / "data" / "agent_config.json"
    if not config_path.exists():
        return {"agent_id": agent_id, "config": {}}

    try:
        configs = json.loads(config_path.read_text(encoding="utf-8"))
        agent_config = configs.get(agent_id, {})
        return {"agent_id": agent_id, "config": agent_config}
    except (json.JSONDecodeError, IOError):
        return {"agent_id": agent_id, "config": {}}
