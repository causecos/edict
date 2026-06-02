import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store';
import { api } from '../api';

const FALLBACK_MODELS = [
  { id: 'anthropic/claude-sonnet-4-6', l: 'Claude Sonnet 4.6', p: 'Anthropic' },
  { id: 'anthropic/claude-opus-4-5', l: 'Claude Opus 4.5', p: 'Anthropic' },
  { id: 'anthropic/claude-haiku-3-5', l: 'Claude Haiku 3.5', p: 'Anthropic' },
  { id: 'openai/gpt-4o', l: 'GPT-4o', p: 'OpenAI' },
  { id: 'openai/gpt-4o-mini', l: 'GPT-4o Mini', p: 'OpenAI' },
  { id: 'google/gemini-2.5-pro', l: 'Gemini 2.5 Pro', p: 'Google' },
  { id: 'copilot/claude-sonnet-4', l: 'Claude Sonnet 4', p: 'Copilot' },
  { id: 'copilot/claude-opus-4.5', l: 'Claude Opus 4.5', p: 'Copilot' },
  { id: 'copilot/gpt-4o', l: 'GPT-4o', p: 'Copilot' },
  { id: 'copilot/gemini-2.5-pro', l: 'Gemini 2.5 Pro', p: 'Copilot' },
];

const THINKING_OPTIONS = [
  { id: '__default__', label: '跟隨全域預設' },
  { id: 'off', label: 'off' },
  { id: 'minimal', label: 'minimal' },
  { id: 'low', label: 'low' },
  { id: 'medium', label: 'medium' },
  { id: 'high', label: 'high' },
  { id: 'xhigh', label: 'xhigh' },
  { id: 'adaptive', label: 'adaptive' },
  { id: 'max', label: 'max' },
];

const CHANNELS = [
  { id: 'feishu', label: '飛書 Feishu' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'wecom', label: '企業微信 WeCom' },
  { id: 'discord', label: 'Discord' },
  { id: 'slack', label: 'Slack' },
  { id: 'signal', label: 'Signal' },
  { id: 'tui', label: 'TUI (終端)' },
];

export default function ModelConfig() {
  const agentConfig = useStore((s) => s.agentConfig);
  const changeLog = useStore((s) => s.changeLog);
  const loadAgentConfig = useStore((s) => s.loadAgentConfig);
  const toast = useStore((s) => s.toast);

  const [selMap, setSelMap] = useState<Record<string, string>>({});
  const [thinkSelMap, setThinkSelMap] = useState<Record<string, string>>({});
  const [statusMap, setStatusMap] = useState<Record<string, { cls: string; text: string }>>({});
  const [thinkStatusMap, setThinkStatusMap] = useState<Record<string, { cls: string; text: string }>>({});
  const [channelSel, setChannelSel] = useState('feishu');
  const [channelStatus, setChannelStatus] = useState('');

  useEffect(() => {
    loadAgentConfig();
  }, [loadAgentConfig]);

  const visibleAgents = useMemo(() => {
    return (agentConfig?.agents || []).filter((ag) => ag.id !== 'main');
  }, [agentConfig]);

  useEffect(() => {
    if (visibleAgents.length) {
      const m: Record<string, string> = {};
      const t: Record<string, string> = {};
      visibleAgents.forEach((ag) => {
        m[ag.id] = ag.model;
        t[ag.id] = ag.thinkingDefault || '__default__';
      });
      setSelMap(m);
      setThinkSelMap(t);
    }
    if (agentConfig?.dispatchChannel) {
      setChannelSel(agentConfig.dispatchChannel);
    }
  }, [visibleAgents, agentConfig]);

  if (!agentConfig?.agents) {
    return <div className="empty" style={{ gridColumn: '1/-1' }}>⚠️ 請先啓動本地服務器</div>;
  }

  const models = agentConfig.knownModels?.length
    ? agentConfig.knownModels.map((m) => ({ id: m.id, l: m.label, p: m.provider }))
    : FALLBACK_MODELS;

  const handleSelect = (agentId: string, val: string) => {
    setSelMap((p) => ({ ...p, [agentId]: val }));
  };

  const handleThinkSelect = (agentId: string, val: string) => {
    setThinkSelMap((p) => ({ ...p, [agentId]: val }));
  };

  const resetMC = (agentId: string) => {
    const ag = visibleAgents.find((a) => a.id === agentId);
    if (ag) {
      setSelMap((p) => ({ ...p, [agentId]: ag.model }));
      setThinkSelMap((p) => ({ ...p, [agentId]: ag.thinkingDefault || '__default__' }));
    }
  };

  const applyModel = async (agentId: string) => {
    const model = selMap[agentId];
    if (!model) return;
    setStatusMap((p) => ({ ...p, [agentId]: { cls: 'pending', text: '⟳ 提交中…' } }));
    try {
      const r = await api.setModel(agentId, model);
      if (r.ok) {
        setStatusMap((p) => ({ ...p, [agentId]: { cls: 'ok', text: '✅ 已提交，Gateway 重啓中（約5秒）' } }));
        toast(agentId + ' 模型已更改', 'ok');
        setTimeout(() => loadAgentConfig(), 5500);
      } else {
        setStatusMap((p) => ({ ...p, [agentId]: { cls: 'err', text: '❌ ' + (r.error || '錯誤') } }));
      }
    } catch {
      setStatusMap((p) => ({ ...p, [agentId]: { cls: 'err', text: '❌ 無法連接服務器' } }));
    }
  };

  const applyThinking = async (agentId: string) => {
    const thinking = thinkSelMap[agentId] || '__default__';
    setThinkStatusMap((p) => ({ ...p, [agentId]: { cls: 'pending', text: '⟳ 提交中…' } }));
    try {
      const r = await api.setThinking(agentId, thinking);
      if (r.ok) {
        setThinkStatusMap((p) => ({ ...p, [agentId]: { cls: 'ok', text: '✅ THINK 已提交，Gateway 重啓中（約5秒）' } }));
        toast(agentId + ' THINK 已更改', 'ok');
        setTimeout(() => loadAgentConfig(), 5500);
      } else {
        setThinkStatusMap((p) => ({ ...p, [agentId]: { cls: 'err', text: '❌ ' + (r.error || '錯誤') } }));
      }
    } catch {
      setThinkStatusMap((p) => ({ ...p, [agentId]: { cls: 'err', text: '❌ 無法連接服務器' } }));
    }
  };

  return (
    <div>
      <div className="model-grid">
        {visibleAgents.map((ag) => {
          const sel = selMap[ag.id] || ag.model;
          const changed = sel !== ag.model;
          const thinkSel = thinkSelMap[ag.id] || '__default__';
          const thinkCurrent = ag.thinkingDefault || '__default__';
          const thinkChanged = thinkSel !== thinkCurrent;
          const st = statusMap[ag.id];
          const stThink = thinkStatusMap[ag.id];
          return (
            <div className="mc-card" key={ag.id}>
              <div className="mc-top">
                <span className="mc-emoji">{ag.emoji || '🏛️'}</span>
                <div>
                  <div className="mc-name">
                    {ag.label}{' '}
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>{ag.id}</span>
                  </div>
                  <div className="mc-role">{ag.role}</div>
                </div>
              </div>
              <div className="mc-cur">
                模型: <b>{ag.model}</b>
              </div>
              <select className="msel" value={sel} onChange={(e) => handleSelect(ag.id, e.target.value)}>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.l} ({m.p})
                  </option>
                ))}
              </select>
              <div className="mc-btns">
                <button className="btn btn-p" disabled={!changed} onClick={() => applyModel(ag.id)}>
                  應用模型
                </button>
                <button className="btn btn-g" onClick={() => resetMC(ag.id)}>
                  重置
                </button>
              </div>
              {st && <div className={`mc-st ${st.cls}`}>{st.text}</div>}

              <div className="mc-cur" style={{ marginTop: 10 }}>
                THINK: <b>{ag.thinkingDefault || `跟隨全域（${agentConfig.defaultThinking || '未設定'}）`}</b>
              </div>
              <select className="msel" value={thinkSel} onChange={(e) => handleThinkSelect(ag.id, e.target.value)}>
                {THINKING_OPTIONS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id === '__default__'
                      ? `跟隨全域預設（${agentConfig.defaultThinking || '未設定'}）`
                      : m.label}
                  </option>
                ))}
              </select>
              <div className="mc-btns">
                <button className="btn btn-p" disabled={!thinkChanged} onClick={() => applyThinking(ag.id)}>
                  應用 THINK
                </button>
              </div>
              {stThink && <div className={`mc-st ${stThink.cls}`}>{stThink.text}</div>}
            </div>
          );
        })}
      </div>

      {/* Dispatch Channel 配置 */}
      <div style={{ marginTop: 24, marginBottom: 8 }}>
        <div className="sec-title">派發渠道</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
          <select className="msel" value={channelSel} onChange={(e) => setChannelSel(e.target.value)}
            style={{ maxWidth: 220 }}>
            {CHANNELS.map((ch) => (
              <option key={ch.id} value={ch.id}>{ch.label}</option>
            ))}
          </select>
          <button className="btn btn-p" disabled={channelSel === (agentConfig?.dispatchChannel || 'feishu')}
            onClick={async () => {
              try {
                const r = await api.setDispatchChannel(channelSel);
                if (r.ok) { setChannelStatus('✅ 已保存'); toast('派發渠道已切換', 'ok'); loadAgentConfig(); }
                else setChannelStatus('❌ ' + (r.error || '失敗'));
              } catch { setChannelStatus('❌ 無法連接'); }
              setTimeout(() => setChannelStatus(''), 3000);
            }}>應用</button>
          {channelStatus && <span style={{ fontSize: 12, color: channelStatus.startsWith('✅') ? 'var(--success)' : 'var(--danger)' }}>{channelStatus}</span>}
        </div>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>自動派發時使用的 OpenClaw 通知渠道（需已在 openclaw.json 中配置對應 channel）</div>
      </div>

      {/* Change Log */}
      <div style={{ marginTop: 24 }}>
        <div className="sec-title">變更日誌</div>
        <div className="cl-list">
          {!changeLog?.length ? (
            <div style={{ fontSize: 12, color: 'var(--muted)', padding: '8px 0' }}>暫無變更</div>
          ) : (
            [...changeLog]
              .reverse()
              .slice(0, 15)
              .map((e, i) => (
                <div className="cl-row" key={i}>
                  <span className="cl-t">{(e.at || '').substring(0, 16).replace('T', ' ')}</span>
                  <span className="cl-a">{e.agentId}</span>
                  <span className="cl-c">
                    <b>{e.oldModel}</b> → <b>{e.newModel}</b>
                    {e.rolledBack && (
                      <span
                        style={{
                          color: 'var(--danger)',
                          fontSize: 10,
                          border: '1px solid #ff527044',
                          padding: '1px 5px',
                          borderRadius: 3,
                          marginLeft: 4,
                        }}
                      >
                        ⚠ 已回滾
                      </span>
                    )}
                  </span>
                </div>
              ))
          )}
        </div>
      </div>
    </div>
  );
}
