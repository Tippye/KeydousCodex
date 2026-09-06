# Codex Windows 宠物与状态输入核实

调查日期：2026-09-06。只读调查；没有修改 Codex 配置、宠物或会话文件，没有启动新的 Codex 回合。结论适用于本机 `OpenAI.Codex 26.901.5280.0`，应用升级后需重新验证内部资源格式。

## 本机资源

安装目录：`C:\Program Files\WindowsApps\OpenAI.Codex_26.901.5280.0_x64__2p2nqsd0c76g0`。

内置资源位于其 `app\resources\app.asar`，不是用户宠物目录。ASAR 内路径为 `webview/assets/`，已核实九种内置宠物：codex、dewey、fireball、hoots、rocky、seedy、stacky、bsod、null-signal。默认 Codex 图片是 `codex-spritesheet-v6-51045ae208c0.webp`；文件名中的 v6 与 manifest 的 spriteVersionNumber 无关。九个内置 WebP 的 VP8L 图像头均为 **1536×2288**，内置目录声明均为 spriteVersionNumber 2。

| ID | displayName | `webview/assets/` 下的文件 |
| --- | --- | --- |
| codex | Codex | codex-spritesheet-v6-51045ae208c0.webp |
| dewey | Dewey | dewey-spritesheet-v5-f5285016f310.webp |
| fireball | Fireball | fireball-spritesheet-v5-9c2a4146d3f9.webp |
| hoots | Hoots | hoots-spritesheet-v8-21cacd193ace.webp |
| rocky | Rocky | rocky-spritesheet-v5-97b5d14cdd54.webp |
| seedy | Seedy | seedy-spritesheet-v10-0f6f906a2aec.webp |
| stacky | Stacky | stacky-spritesheet-v6-18d0359c82af.webp |
| bsod | BSOD | bsod-spritesheet-v5-cc54136ce042.webp |
| null-signal | Null Signal | null-signal-spritesheet-v7-1e7dbf89200f.webp |

`C:\Users\Payne\.codex\pets` 在默认沙盒内访问被拒绝；必要的提权只读列举已成功，目录为空。未读取当前选中宠物配置，因此不能声称用户当前选中了 Codex。桥接应提供自己的宠物选择，默认值写明为本程序默认。

## 自定义 manifest

本机解析器读取 `pets/<directory>/pet.json`，并兼容旧的 `avatars/<directory>/avatar.json`。不是 `manifest.json`。

| 字段 | 本机解析行为 |
| --- | --- |
| id | 可选，非空字符串；仅作为显示名候选，实际自定义 ID 是 `custom:<directory>` |
| displayName | 可选，非空字符串 |
| description | 可选或 null，去掉首尾空白，空白变 null |
| spriteVersionNumber | 1 或 2，默认 1 |
| spritesheetPath | 非空相对路径，默认 `spritesheet.webp`；必须保持在宠物目录内 |

允许 PNG 或 WebP，校验实际图像尺寸。版本 1 为 1536×1872；版本 2 为 1536×2288。桥接读取路径还应解析真实路径，拒绝通过符号链接跳出所选目录。

## 帧布局

两版均为 **8 列，每格 192×208**。版本 1 有 9 行，版本 2 有 11 行。裁剪第 r 行、第 c 列的矩形为 `(c*192, r*208, (c+1)*192, (r+1)*208)`。不要把未使用的尾部格子加入动画。

| 行（0 起） | 本机动画名 | 有效帧数 | 每帧毫秒 / 最后一帧毫秒 |
| --- | --- | --- | --- |
| 0 | idle | 6 | 280, 110, 110, 140, 140, 320 |
| 1 | running-right | 8 | 120 / 220 |
| 2 | running-left | 8 | 120 / 220 |
| 3 | waving | 4 | 140 / 280 |
| 4 | jumping | 5 | 140 / 280 |
| 5 | failed | 8 | 140 / 240 |
| 6 | waiting | 6 | 150 / 260 |
| 7 | running | 6 | 120 / 220 |
| 8 | review | 6 | 150 / 280 |
| 9、10（仅 v2） | 16 个方向的 look frame | 各 8 | 按方向选静态帧 |

本机普通 idle 播放使用上表 idle 时长乘 6；其他动画播放三遍后接 idle 循环。减少动态效果时仅显示首帧。桥接可提供简化播放，但应明确它是桥接渲染策略，不能虚称复制完整桌面行为。

桥接状态到动画的建议映射属于产品选择：idle→idle，thinking→review，working→running，waiting→waiting，success→waving，error→failed。桌面宠物没有名为 thinking 或 success 的对应行。

## 现有桌面任务的可观测状态

限定读取当前主任务的单个 rollout：`C:\Users\Payne\.codex\sessions\2026\09\06\rollout-2026-09-06T11-25-16-01a074bf-b5b0-7f31-aacb-59a281c2d95a.jsonl`。调查只输出事件种类、时间戳、turn ID 和字段名，没有输出聊天、命令、推理正文或工具结果。

实际观察到以下内部 JSONL 元数据：

- 顶层 `type=event_msg`，payload.type 为 `task_started`：具有 turn_id、started_at。
- `task_complete`：具有 turn_id、started_at、completed_at、duration_ms；另有最后回复字段，桥接应忽略其内容。
- `item_completed`：具有 thread_id、turn_id、item、started_at_ms、completed_at_ms。item.type 实测包含 Reasoning、CommandExecution、McpToolCall、FileChange、AgentMessage、UserMessage、Extension、SubAgentActivity。
- 还有 token_count、thread_settings_applied；不用它们推断具体工作状态。

建议只追踪用户明确选择的任务文件；不要自动跟随整个 sessions 目录中最新修改的文件，多 agent 会使选择错误。完整行 JSON 解析不可避免会短暂读入该行，但归一化后只保留白名单元数据，不记录原始行。应支持尾部半行缓存、文件截断/替换、大小限制与过期判定。

保守状态语义：task_started 表示回合已开始，可显示 working；task_complete 表示回合结束，可短暂显示 DONE（不保证任务目标成功）。item_completed 只证明刚才完成了某类活动，不能证明此刻仍在思考或运行命令。工具非零退出不能直接当作整个回合失败。启动时历史完成事件不应触发新完成通知。长期无新事件应标记有效性 stale/unknown，不能猜 waiting、error 或 idle。

本次未在所选 rollout 观察到可靠的等待审批、等待用户输入或系统错误事件，不能宣称桌面六种状态均可精确获取。

turn ID 核验：实际观察到三次 task_started，前两次各有同 ID 的 task_complete，第三次仍在运行。76 条 item_completed 的 turn_id 全部匹配当时最近一次 task_started；item_completed 另有 thread_id，task_started/task_complete 本次只有 turn_id，需要从所选文件身份固定 thread ID。实现应先过滤文件/任务身份，再用 active turn ID 过滤 item_completed、完成及任何终止事件，避免迟到的旧事件覆盖新回合。开始时间和完成时间是 Unix 秒；外层 timestamp 为 ISO 8601 UTC。

应用打包代码有 `codex/event/turn_aborted` 名称，但所选 rollout 未发生中断，本调查没有确认其持久化 payload 字段及原因枚举。不能把这个名称存在当作已实测支持。若未来兼容处理遇到 turn_aborted，仅在存在匹配 active turn ID 时将回合标记 interrupted/unknown，停止活动指示；不能映射成 success，也不能以中断证明任务错误。缺 ID 的未知终止事件不应关闭当前新回合。其他未知事件忽略并记录事件名计数即可，不能记录原文。

## 公开接口与 CLI 边界

[公开 App Server](https://learn.chatgpt.com/docs/app-server) 提供 thread/status/changed，状态包括 notLoaded、idle、systemError、active；active 示例含 waitingOnApproval，turn/completed 可区分 completed、interrupted、failed。该协议有能力表达更精确状态，但必须连接管理该任务的同一个运行时。另起 app-server 不会因此成为现有桌面运行时的观察器，thread/resume 也不是无副作用订阅。

本机 CLI 为 `C:\Users\Payne\AppData\Local\OpenAI\Codex\bin\27d6a192e9c98618\codex.exe`。`app-server --help` 列出 stdio、unix、ws 等传输；实际运行只读 `app-server daemon version` 返回：`codex app-server daemon lifecycle is only supported on Unix platforms`。因此本调查没有建立 Windows 桌面运行时的公开外部订阅连接；不要为了桥接开启远程控制、另起 daemon 或修改 Codex 配置。

[CLI 非交互 JSONL](https://learn.chatgpt.com/docs/non-interactive-mode) 是独立格式：thread.started、turn.started、turn.completed、turn.failed、item.*、error。它描述被该 exec 调用运行的任务，不能拿来观察现有桌面任务。适配器应分成 desktop-rollout 和 cli-jsonl，禁止根据相似名称混用。

[官方宠物说明](https://learn.chatgpt.com/docs/pets) 解释桌面显示 Running、Needs input、Ready、Blocked，多任务优先顺序为需输入、阻塞、就绪、运行。这是桌面自身可访问运行时状态后的产品行为，不证明 rollout 拥有相同信息。公开网页目前只列出 Web 上传尺寸 1536×1872；桌面 v2 的依据是上述本机资源。

## 最小 Python 边界建议

`PetAsset` 保存来源、显示名、版本、图像尺寸和图片读取入口；`load_pet(directory)` 与 `load_builtin(asar_path, pet_id)` 只读载入，通过尺寸后输出统一对象。内置资源按 ASAR 索引和已识别资源名读取，不解包整个应用、不执行其 JS、不修改安装目录。升级后找不到资源应报可理解错误。

ASAR 最小安全读取算法：打开选定 app.asar 为二进制只读，读取前 16 字节的四个小端 uint32；本机值为 `(4, 2430392, 2430388, 2430383)`。从文件偏移 16 读取第四个值长度的 JSON 索引；数据区起点为 `8 + 第二个值`。逐层在索引的 files 字典中找到固定资源路径，仅接受普通 packed 条目（有非负十进制 offset、非负 size，无 link，无 unpacked），读取 `数据区起点 + offset` 开始的 size 字节。开始读取前限制索引大小、资源大小，确认所有范围位于实际文件长度内，并校验解码后的真实 PNG/WebP 尺寸。不要用索引内容构造 shell 命令，不把索引中的任意路径写入文件系统。

可配置用户显式选择的 ASAR 路径；自动发现应只在已确认 OpenAI.Codex Appx 的安装目录寻找 `app/resources/app.asar`。资产匹配只接受上述宠物 ID，资源名遵守 `<id>-spritesheet-*.webp` 且位于 `webview/assets/`，多个匹配时明确失败或让用户选择，不随意挑选。不要把本机带版本号的安装路径硬编码成跨升级永久位置。

`StatusEvent` 仅保存 state、source、thread_id、turn_id、observed_at、validity（observed/inferred/stale/unknown）和简短 reason。`DesktopRolloutSource(path)` 与 `CliJsonlSource(stream)` 分别解析自身格式。`snapshot(now)` 应保留最后观察时间，过期不伪造新事件。可手动选择状态演示渲染；界面明确显示 manual，与真实任务观察分开。

## 本机证据指纹

以下为 ASAR 内原始文件 SHA-256；未把第三方打包代码复制入项目：

- `.vite/build/src-VqXTPopo.js`：`8d056524ea3f5714e5e0a254afd88f018d58465bc6ea026adee3c80ff7799e29`（manifest 与图片头解析）。
- `webview/assets/app-initial-ffce11d82782.js`：`30bfcbdbc47b90bc72fa8853e949dce2eee6b519d3876113260c939801f17203`（布局、动画、内置目录）。
- `webview/assets/codex-pet-assets-16127cbc3056.js`：`5e7efb74df8ab0264318942a2b2aa5d496c507ffe3c8957cc9bf8fc967d40cb9`（资源名映射）。
