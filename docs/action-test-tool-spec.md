# 任务书:动作接口真机测试工具(控制类功能端到端验证)

> ✅ **已实现并真机验收(2026-06-23,本地未提交)**:`web/action-test.html` + `GET /action-test` + `GET /api/action-state`(`server/app.py::_action_state` + `actions.controllable_inventory`)。后续**扩成全 kind 覆盖**(开关/锁/窗帘/空调/媒体/选择/数值/按钮/场景/安防,按域分组 + 只读传感器折叠 + 搜索),`actions._resolve_action` 同步扩白名单。真机已验:开关/窗帘/空调(含调温调模式)/torrent 暂停(qB+Transmission)。
> ⚠️ **本文下方仍写了打印机 pause/resume/stop——那部分已作废**:真机实测 HA 拓竹云模式控制不了打印机,**打印机控制已整体移除**(测试台打印机改纯只读)。详见记忆 `bambu-ha-cloud-offline-quirk`。
>
> **交付对象**:接手的开发者/AI。本文自包含。
> **背景**:看板的「点击控制设备」动作接口(HA 开关 / 3D 打印机 / PT 下载)**只做过单元+curl 测试,没有人点着按钮、对着真设备确认过它真的控制成功**。需要一个简单的测试网页,把每个控制点都点一遍、看「点前状态 → 点后状态」是否真变了。

---

## 0. 现状:已有什么、缺什么

**动作接口(已上线,`server/actions.py` + `server/app.py`,均经访问令牌)**:
| 接口 | body | 白名单 action |
|---|---|---|
| `POST /api/action/ha` | `{entity_id, action}` | `toggle/on/off`(lock→lock/unlock、cover→open/close/toggle 内部映射) |
| `POST /api/action/torrent` | `{client, id, action}` | `pause/resume`(按 client 名路由到 qB/Transmission adapter) |

**缺口**:
- App 里虽有控制按钮(`target=android`),但点了之后**没有「点前/点后状态对照」**,不好确认到底控没控住。
- torrent 目前**只有 pause/resume**,没有 删除/重新校验/优先级。
- 早期真机测试时**打印机离线**,pause/resume/stop 只验到「button 实体存在 + 服务路径通」,**没在真打印中验过**。

**真机环境**(内网,真实地址只在内部任务板 `CLAUDE_TASK_QUEUE.md`,不入库):HA / qB(:8085)/ Transmission(:9091)在同一台 NAS(`192.168.x.x`);打印机经 HA(拓竹)。

---

## 1. 要做的:一个「控制台测试页」

新增 `web/action-test.html` + 路由 `GET /action-test`(**经令牌,绝不豁免**——能改你家设备)。页面:

1. **列出每个可控目标 + 当前状态**:
   - HA:遍历 `ha.cards`(从 `/app/page/ha` 的数据或新开个 `/api/action-state` 紧凑状态接口),每个实体显示 名称/当前状态 + 按钮(toggle/on/off,锁和窗帘显对应动作)。
   - 打印机:显示在线/状态/进度 + 按钮 pause/resume/stop。
   - 下载:遍历每个 client 的每个种子,显示 名称/状态/进度 + 按钮 pause/resume。
2. **点按钮 → POST 对应 `/api/action/*` → 显示原始返回(ok/error)→ 隔 1~2s 重新拉状态 → 把「点前→点后」并排显示**(这是关键:肉眼确认设备真的响应了)。
3. 出错把 HA/qB/Transmission 返回的错误原样显示(方便定位是鉴权/实体名/网络哪里的问题)。

> 实现可极简:纯 HTML+fetch,不引框架;令牌从 `?token=` 读、所有请求带 `X-Access-Token`。也可不做新页、直接在 App 的控制页上加「状态对照」——但独立测试页更利于隔离验证。

可能需要的小服务端补充:一个 `GET /api/action-state`(经令牌)返回各可控目标的当前状态紧凑 JSON(HA 实体 on/off、打印机 状态、种子 状态/进度),供测试页拉「点前/点后」。**注:这个端点和 V3「看板播报」要的 `/api/app-state` 高度重合,可合并设计。**

---

## 2. 真机验收清单(逐项点 + 确认设备真响应)

- **HA**:每个实体 toggle → HA 后台 + 设备真的开/关、看板下一轮也变 → 再 toggle 复原;on/off 幂等;lock 锁/解锁、cover 开/合走对的 service 不报错。
- **打印机(必须有一个正在打印的任务)**:pause → 打印机真暂停、状态变 paused → resume → 继续 → **stop → 当前打印终止**(⚠️ 破坏性,拿废件验)。顺便确认 stop 是不是用户要的「取消任务」语义;不是的话定是否加独立 cancel。
- **下载**:每个 client 每个种子 pause → qB/Transmission 界面里真的暂停 → resume → 恢复下载/做种。两个 client 都要验。

## 3. 安全 / 红线
- `/action-test`、`/api/action/*`、`/api/action-state` **全经令牌,绝不进 `_AUTH_EXEMPT_*`**(能改设备)。
- 仍只接受**白名单** action,不透传任意 service/命令。
- printer `stop` 是破坏性的,测试页对 stop **二次确认**(同 App)。
- 真机 IP/凭据**不进公开仓库**(内网信息只在内部任务板/记忆)。
