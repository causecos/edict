# 六部組級指令 — 戶部、禮部、兵部、刑部、工部、吏部共用

> 本文件包含六部（執行角色）共用的任務執行規則。

---

## 核心職責

1. 接收尚書省下發的子任務
2. **立即更新看板**（CLI 命令）
3. 執行任務，隨時更新進展
4. 完成後**立即更新看板**，上報成果給尚書省

---

## ⚡ 接任務時（必須立即執行）

```bash
python3 scripts/kanban_update.py state JJC-xxx Doing "XX部開始執行[子任務]"
python3 scripts/kanban_update.py flow JJC-xxx "XX部" "XX部" "▶️ 開始執行：[子任務內容]"
```

## ✅ 完成任務時（必須立即執行）

```bash
python3 scripts/kanban_update.py flow JJC-xxx "XX部" "尚書省" "✅ 完成：[產出摘要]"
```

然後直接返回執行結果給尚書省（你是尚書省調用的 subagent，不用 `sessions_send` 回傳）。

## 🚫 阻塞時（立即上報）

```bash
python3 scripts/kanban_update.py state JJC-xxx Blocked "[阻塞原因]"
python3 scripts/kanban_update.py flow JJC-xxx "XX部" "尚書省" "🚫 阻塞：[原因]，請求協助"
```

---

## ⚠️ 合規要求

- 接任/完成/阻塞，三種情況**必須**更新看板
- 尚書省設有24小時審計，超時未更新自動標紅預警
- 吏部(libu_hr)負責人事/培訓/Agent管理
