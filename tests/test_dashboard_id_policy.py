"""Dashboard ID policy regression tests."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_HTML = ROOT / "dashboard" / "dashboard.html"


def test_dashboard_html_keeps_jjc_for_edicts_and_oc_mc_for_sessions():
    """正式任務走 JJC；系統會話保留 OC/MC prefix。"""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert "function isEdict(t){ return /^JJC-/i.test(t.id||'') || /^[0-9a-f]{8}-/i.test(t.id||'') }" in html
    assert "function isSession(t){ return /^(OC-|MC-)/i.test(t.id||'') }" in html


def test_dashboard_memorial_views_count_only_jjc_tasks():
    """奏摺統計與奏摺記憶庫都應只看 JJC 正式任務。"""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert "const jjc = tasks.filter(t=>(t.id||'').startsWith('JJC-'));" in html
    assert "let mems = tasks.filter(t=>(t.id||'').startsWith('JJC-') && ['Done','Cancelled'].includes(t.state));" in html


def test_dashboard_session_views_keep_only_visible_agents_and_canonicalize_aliases():
    """小任務面板只顯示看板允許的 agent，並把 main alias 視為太子。"""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert "const DASHBOARD_VISIBLE_AGENT_IDS = ['taizi','zhongshu','menxia','shangshu','hubu','libu','bingbu','xingbu','gongbu','libu_hr'];" in html
    assert "const DASHBOARD_AGENT_ALIASES = {main:'taizi'};" in html
    assert "const sessions = tasks.filter(t=>!isEdict(t)).filter(t=>isDashboardVisibleAgent(extractAgent(t)));" in html
    assert "if(m) return canonicalDashboardAgentId(m[1]);" in html
