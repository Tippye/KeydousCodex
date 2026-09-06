# Keydous Codex Bridge for Windows

这是基于 [Keyphore](https://github.com/BarryBarrywu/Keyphore) 的 Windows
适配版，版本 `0.3.0`。它是一个独立的第三方 Windows 桌面应用：主程序提供独立窗口，
通过官方 Keydous IoT 驱动的本机服务（`127.0.0.1:3814`）访问键盘；可选的
Codex 插件只负责把任务生命周期事件交给桥接程序。它不是 Keydous 官方驱动，也不是
官方驱动的插件。

当前实验性写入允许列表只有 **NJ98、USB、有线、驱动型号 ID `1021`**。程序可识别
部分其他型号，但不会对它们写屏幕或灯光。NJ98 的实际协议参数为 `160×80` RGB565；
动画上传到用户明确选择的 GIF 槽位 1–3，每个动画最多 50 帧。程序不刷写固件，也不
提供任意协议命令入口。

## 已实现的功能

0.3.0 默认使用 WebView2 桌面窗口承载同一套界面，无浏览器地址栏，无需打开浏览器。支持窗口缩放、原生下载保存对话框、重复启动激活已有窗口；关闭窗口会停止主服务、恢复已启用联动的 RGB，并释放设备所有权。外观偏好保存在应用数据目录的 `desktop-profile` 中。

0.2.0 将界面调整为 Keyphore 原版的紧凑状态首页和分组设置流程：齿轮进入显示、设备、集成、改键及通用设置。Windows 和浏览器使用同一套界面，支持跟随系统/浅色/深色。Keydous 的屏幕预览和改键是新增内容；原版 NuPhy 专用灯效不冒充 Keydous 功能。

在“改键”中先读取当前键盘，再选择普通层/Fn 层、按键或旋钮动作并应用。每次只写一个控件，自动保存带设备身份和校验和的完整两层备份；写后重读验证。恢复入口恢复本程序改动前的配置，遇到外部工具修改会中止，避免覆盖未知内容。普通层与 Fn 层均已在 NJ98 USB 实机上验证单键写入和完整恢复；这不等同于每种动作的物理按键触发验收。

macOS 使用相同业务代码和界面，原生 Fn/Globe 控制放在同一改键页；系统组件源码位于 `../macos/`。`Build-Mac.sh` 在 Mac 上构建同一 `.app`，并集成内部组件。当前没有 Mac 编译、签名、授权和键盘实测证据，因此不发布“已验证的 Mac 安装包”。Windows 不会安装或运行 Mac 输入组件。

- 导入本机 Codex 宠物，或导入自定义 `pet.json` 与 PNG/WebP spritesheet。发布包不
  附带 Codex 的宠物资源。
- 在 `160×80` 预览和导出中组合宠物、Codex 状态标签、Windows NUM/CAPS 锁定状态、
  当前连接类型与电量。驱动没有返回电量时显示未知；程序不会把 USB 状态伪装成
  蓝牙编号或 2.4G 状态。
- 把当前画面快照上传到 NJ98 的 GIF 槽位。上传会覆盖所选槽位，需在界面中明确确认。
- RGB 状态联动为每次运行单独选择的功能，最短更新间隔为 10 秒。启用前持久化原始
  7 字节设置，退出时精确恢复；异常中断留下恢复日志，下一次启动可继续恢复。
- 支持手动状态、明确选择的 Codex Desktop JSONL、CLI JSONL 文件，以及默认的
  Keyphore Hook 聚合。Hook 聚合优先级为等待回应、执行中、完成提示、空闲；活动
  TTL 为 3600 秒，完成提示为 5 秒。

Hook 的 `Stop` 表示一轮结束，不代表任务目标已成功。`PermissionRequest` 能表示审批
等待，但不会覆盖所有向用户提问的情况，也没有稳定的自动“错误” Hook，因此程序不
伪造错误状态。Hook 进程必须接收 Codex 提供的完整标准输入 JSON，但只提取并保存
`hook_event_name`、`session_id`、`agent_id`、`turn_id` 四种允许字段和本地产生的状态
时间戳；任务正文、回复正文、工具名称和工具参数不会被持久化或转发。

## 安装和启动

需要 Windows 10/11、Microsoft Edge WebView2 Runtime，以及已安装并正在运行的
Keydous IoT 驱动。发布的 EXE 已包含 Python，无需另外安装 Python。请先让官方驱动
能够正常识别 NJ98。源码运行和构建才需要 Python 3.12。

下载 Windows ZIP 后先完整解压，双击文件夹内的 `KeydousCodex.exe`；不要仅复制 EXE，
同目录的 `_internal` 与 Hook 程序也需要保留。

源码方式：

```powershell
cd Keyphore\windows
.\Setup.ps1
.\Start-Bridge.cmd
```

已有构建产物时，双击 `Start-Bridge.cmd` 或直接运行
`dist\KeydousCodex\KeydousCodex.exe`。程序直接显示 Windows 桌面窗口，内部服务只监听
本机回环地址。右上角关闭按钮或设置中的退出会结束主程序；它不会注册开机启动。
只有明确传入 `--browser` 才打开旧浏览器界面，`--no-browser` 用于无窗口运行和自动验收。

首次使用建议按以下顺序操作：

1. 在设备列表中核对 NJ98 并明确连接。
2. 导入宠物，检查预览和锁定键／连接／电量栏。
3. 在界面中审阅八个 Codex Hook 的事件、命令和数据字段，再勾选同意并安装。程序只
   信任自己生成的 Hook，不会启动、恢复或批准任何 Codex 任务。
4. 选择一个允许覆盖的 GIF 槽位后上传，并在键盘屏幕上目视确认。
5. 需要 RGB 联动时单独启用；退出主程序会停止联动并恢复灯光。

退出主程序后，已安装的 Hook 仍会继续记录受限的本地元数据，直到在集成页面中禁用或
移除；主程序关闭时不会继续操作键盘。

## 当前硬件验收范围

NJ98 的设备发现、RGB 读取、写入和精确恢复已经在当前机器验证。验证样本的原始 7 字节
值为 `[66, 8, 255, 0, 0, 0, 0]`，工作状态写入值为
`[1, 4, 2, 7, 58, 189, 231]`，随后成功恢复原值。

2026-09-06 用户确认已上传 work 状态动画，并在实际屏幕上正确显示；具体槽号、固件版本
和上传耗时未记录，其他状态及自动切槽尚未验收。官方默认壁纸中的
黑猫、状态栏与宠物属于固件原生页面；目前没有证据证明它支持局部覆盖或实时页面流。
本程序上传的是组合后的完整画面快照／动画，NUM/CAPS、连接和电量反映上传或预览时刻，
不会在键盘屏幕上自行实时刷新。

## Codex Hook 状态

Keyphore Hook 是推荐状态源。集成安装会生成八种 Hook：
`SessionStart`、`SessionEnd`、`UserPromptSubmit`、`PermissionRequest`、
`PostToolUse`、`Stop`、`SubagentStart`、`SubagentStop`。界面会展示具体定义和摘要，只有
用户明确审阅同意后才写入并信任这些定义。专用的 `KeydousCodexHook.exe` 只解析标准
输入并更新本地状态文件，不连接键盘。

状态文件限制为 4 MiB，单个 Hook 输入限制为 1 MiB；最多保存 2048 个状态所有者，每个
所有者最多保留 256 个已结束轮次标记，标识字段最长 256 个字符。达到容量、输入无效或
文件损坏时，Hook 会返回不含任务内容的有界错误，主程序把可信度降为未知，不会静默
删掉旧轮次后继续。

本版本没有状态重置按钮。如果 `hook-state.json` 损坏或需要明确清空，请先在集成页面
禁用 Hook 并退出主程序，再把文件移动为备份，然后重启程序、重新审阅并启用 Hook：

```powershell
$state = Join-Path $env:LOCALAPPDATA 'KeydousCodex\hook-state.json'
$backup = "$state.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
Move-Item -LiteralPath $state -Destination $backup
```

请保留备份，不要直接删除。清空状态会丢失此前轮次的结束标记；重启后的状态明确为
“未知”，直到收到新的有效 Hook 事件。

## 诊断、测试与构建

只读诊断：

```powershell
.\.venv\Scripts\python.exe -m keydous_bridge --diagnose
```

运行测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests\test_web_state.js
```

以上使用 Setup.ps1 创建的目录内虚拟环境；本工作区若复用顶层虚拟环境，则将 Python 路径替换为 `..\..\.venv\Scripts\python.exe`。完整验收边界见 [docs/acceptance.md](docs/acceptance.md)。在交互式 Windows 用户会话中运行 `python Verify-Desktop.py` 验证真实 WebView2 渲染和页面退出，构建后运行 `python Verify-DesktopPackage.py` 验证 EXE 窗口、重复启动和关闭。`python Verify-Package.py` 在隔离 Codex 配置中复验冻结 Hook 生命周期；请先退出正在运行的桥接程序。

构建完整发布包：

```powershell
.\Build.ps1
# 或指定 Python
.\Build.ps1 -Python C:\Python312\python.exe
```

构建使用一次 Analysis/PYZ 生成同目录下的两个程序：无控制台的
`KeydousCodex.exe` 与控制台 Hook 程序 `KeydousCodexHook.exe`。输出包括：

```text
dist\KeydousCodex\
release\KeydousCodex-0.3.0-windows-x64.zip
release\KeydousCodex-0.3.0-source.zip
release\KeydousCodex-0.3.0-SHA256SUMS.txt
```

二进制包带有 GPLv3、Python、Pillow、PyInstaller 和桌面组件许可证原文；对应源码包包含本次
构建所需的完整仓库源码与上游测试夹具，排除 `.git`、虚拟环境、运行数据、构建目录、
缓存和生成的压缩包。

## 许可证

本适配基于 Keyphore 上游提交
`9ca11f275809ebc2649bf365effdee8cc7682084`，沿用 **GPL-3.0-only**。Copyright
(c) 2026 Barry Barry Wu。完整条款见源码根目录的 LICENSE 或二进制包的 licenses/LICENSE；第三方说明见
[THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。分发二进制时请同时提供对应源码包。
