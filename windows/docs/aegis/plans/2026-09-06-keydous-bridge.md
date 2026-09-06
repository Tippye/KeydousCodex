# Keydous Codex Bridge 实施计划

依据：DESIGN.md；用户批准独立程序、复用官方 IoT，并要求完整实现，授权按难度使用 subagents。

起始快照：只有 DESIGN.md，无代码或 Git 仓库。沿用当前目录，不创建分支。代码必要性：官方网页没有 Codex 状态输入或宠物转换，必须新增本地桥接；保留 IoT 为硬件访问唯一入口。

实现边界：Python 本地服务 + 浏览器中文界面；Pillow 图像处理；Windows 一键启动与可打包 exe。核心模块为状态输入、宠物渲染、设备协议、应用编排。HTTP 只绑定 loopback；写入接口校验同源和会话令牌；不暴露任意 HID 命令。配置写入应用数据目录并可移植运行。依赖精简。

TDD 路线：off / skipped；采用实现后的有意义回归测试，重点检查解析、断开、未知能力、动画边界、状态时效和请求权限。

## 工作划分

### 已批准的双平台与 UI 扩展执行段（2026-09-06）

TaskStartSnapshot：沿用当前 Keyphore checkout，Windows 首版运行中；已有用户数据与发布包。根代理管理 Git，子代理只编辑其负责文件。用户已批准内部虚拟 HID，要求尽量沿用 Keyphore UI 和使用方式。TDD off/skipped，实施后针对协议、恢复、权限和状态转换做回归。

1. UI（Sol）：阅读原版 KeyphorePopover/SignalSettingsView/DiagnosticsView 和引导流程；修改 windows/keydous_bridge/web 三个文件，采用紧凑状态首页、设置入口和分组，保留现有控件 ID 与 API；新增改键页。首页不得显示模拟状态为真实状态。验证 Node 状态回归、浏览器窄屏/宽屏、所有功能入口。此任务不编辑 Python。
2. NJ98 改键（根代理）：新增 mapping.py，接入 iot.py 的完整矩阵读和单键写、app.py/server.py 的显式读取/应用/恢复路由。原始两层备份、过期快照拒绝、写后全矩阵校验、失败留恢复记录；UI 不提供原始 HID RPC。tests/test_mapping.py 验证具体包、保留未知槽、失败与恢复、并发和无变化不写入。读取真实 USB 矩阵核实 framing 后才验收单键写。
3. Mac 构建与输入组件：核实官方 Mac IoT/VirtualHIDDevice 依赖和平台入口；共用现有 Python/Web 业务，新增必要原生组件和受限 IPC。调整单实例、Codex 可执行发现、Hook 命令、宠物导入路径、Num/Caps 查询和打包脚本。无 Mac 时仅执行可在 Windows 验证的核心/模拟测试，保留真实构建、签名和输入效果的明确外部验收项。
4. 每段先独立规格审查，再质量审查，修复后运行相关回归。最后重新打包 Windows，在隔离数据目录验证生命周期后更新正在运行的用户界面；不改用户 Hook 信任。

文件边界：UI 代理仅 web/ 与 UI 对照说明；根代理 Python 协议/服务/测试。原生 Mac 后续单个实现代理独立目录，业务状态与硬件访问仍各有唯一所有者。原版 Swift/NuPhy 程序不被当成新的 Keydous 应用发布。保留现有 data，备份有明确 schema，不无条件迁移或删除。

验收限制：Mac 系统与芯片/可用测试条件、可覆盖屏幕槽仍待用户回复；这些不阻止公共逻辑和 Windows 实现，不虚构完成证据。未知型号禁写，原生屏幕覆盖层未验证，禁止使用持久 GIF 反复写入模拟实时刷新。

1. 协议研究（Astra）：确认可用操作和证据，禁止猜测硬件写入；输出 docs/protocol-research.md。
2. Codex 研究（Astra）：确认宠物格式与桌面事件来源，输出 docs/codex-research.md。与 1 独立并行。
3. 主线：建立 keydous_bridge/config.py、server.py、app.py、web/，完成中文面板、预览、设置、导出和本地安全边界。
4. 研究结果确定后，Sol 负责一个有界模块的实现（宠物/事件或设备），与主线使用不同文件。后续分别进行规格与质量审查。
5. 设备模块：grpc-web 帧/protobuf 最小实现、流式发现、型号能力、串行传输与断开处理。图像写入仅执行已核实的官方流程；动态状态不能靠反复Flash写入。RGB独立可选。
6. 端到端：UI驱动预览、导出、连接、读取与经过验证的上传。实机可见效果需要用户观察时请求必要反馈，同时完成不依赖反馈的工作。
7. 打包与文档：README 中文使用说明，启动脚本，requirements、pyproject、测试、exe打包脚本，运行并验证发布产物。

## 验证

- python -m unittest discover -s tests -v
- python -m keydous_bridge --diagnose（只读设备诊断）
- HTTP集成测试：配置持久化、预览/导出、CSRF/路径限制、错误响应。
- 真实运行浏览器界面，检查160×80预览及模式切换。
- NJ98只读实机识别；有据可依的用户图像上传，记录结果；不得把ACK等同于完整屏幕验收。
- 打包后exe启动、health、关闭无残留任务。

## 约束和未知

保持原生状态栏是首选，是否支持取决于实证。没有蓝牙槽号或电量不能补造。桌面状态与CLI输入分开标明。未知型号禁写。固件升级、驱动替换、密钥读取不在范围。

## 检查点

2026-09-06 0.2.0 续接检查点：同一应用+内部虚拟 HID 和原版 UI 对齐已获用户批准。UI Sol 完成392状态首页/分组设置/固件改键页，独立规格与质量审查通过；根代理补 RGB局部保存、掉线状态失效、真实改键render回归并复核通过。普通层/Fn层单键临时写计算器槽90后完整恢复，初始/最终matrixrevision一致，见acceptance.md。固件后端规格/质量均通过。Mac Python路径/Hook/锁/清理平台分支已通过独立规格和质量；新增nativecontroller仍在复核异步健康轮询与退出竞态。macos/原生实现由单个Sol代理完成中，Macspec与Build-Mac.sh根代理负责；没有Mac实机。

本轮用户浏览器有未保存BSOD宠物+RGBtrue草稿，刷新新版后已通过UI恢复草稿，未保存或启用RGB。真实用户当前config pet bridge-cat/layoutdashboard/sourcehooks、RGBfalse，integrationcached显示此前用户已安装信任，不能覆盖用户信任或回退配置。当前运行打包EXE曾启动PID94028，URL47698；后续源码已有修改，最终需正常关闭重建再启动并保留页面草稿。旧版本0.1.0压缩包保留，新增目标0.2.0。

2026-09-06：研究两路并行；主线建立最小单进程应用。未对设备写入。架构审核范围：输入真实性、Flash更新边界、HTTP本地访问、型号匹配、资源与线程清理。

2026-09-06 续接：用户指定 Keyphore 作为基础。克隆提交 `9ca11f275809ebc2649bf365effdee8cc7682084`，此前实现移入 windows/，无并列的第二套程序。新增工作：移植 Keyphore 八类 Hook 的持久状态核心及多 owner 汇总；配置界面提供明确 Hook 审阅、安装、授权和移除。保留原有 macOS/NuPhy 实现。NJ98 协议已通过规格与质量审查；UI 通过静态规格审查；宠物模块8项测试通过，待独立审查及浏览器/硬件验收。

2026-09-06 交付检查点：Windows 程序、Hook 插件安装入口与状态核心、导入/渲染/导出、精确 NJ98 协议、RGB 恢复、中文界面、打包与源码包已实现。最终独立规格/质量复核通过；53项普通 Python 测试、JS异步状态回归、隔离真实 Codex 生命周期及打包 EXE 生命周期通过。研究曾误取基类 RGB 命令，实机失败后完整追踪继承链，修正为 0x07/0x87；配置0/1报告率只读核查均1000Hz，正确RGB写入/原值恢复通过。此纠错使早期静态协议审查不能作为实机验收依据。完整证据见 docs/acceptance.md。

待用户输入：选择可覆盖的用户动画槽并观察实屏。真实 Codex Hooks 尚需用户在完成的审阅界面启用。原生动态状态层和更多型号缺少固件/硬件证据，明确保留为未验证范围。

2026-09-06 双平台新增范围调查：用户要求全部功能完成并测试后适配 Windows/macOS，将 Karabiner 的 Mac Fn 能力集成到同一应用。Astra 两路研究已完成，见 docs/nj98-mapping-research.md 和 docs/macos-fn-research.md。NJ98 单键普通/Fn 改键路径、101 个可见控件 slot 已核对；尚未发送改键命令。Mac 完整 Fn/Globe 需要虚拟 HID，Quartz 不能提供完整等价行为。DESIGN.md 已更新当前交付状态并写入同一应用 + 应用管理的原生组件方案，新增特权组件设计待确认。当前没有 Mac 实机环境；原 Windows 发布包保持不变。下一步在设计确认后细化分段实施和恢复测试，不把研究文档当作已交付功能。


2026-09-06 0.2.0 最终公共代码检查点（更新前述历史状态）：用户已批准同一应用和内部虚拟 HID。Keyphore 风格 UI、NJ98 普通/Fn 层改键、跨平台公共代码与 Mac 控制接口已完成。79 项 Python 测试中 78 通过、1 项可选真实测试跳过；Node 回归通过；重新构建的 EXE 在隔离 CODEX_HOME 中通过真实 Hook 安装/信任/执行/移除和正常退出。正常关闭旧 EXE 后启动新 EXE PID96384，health=0.2.0；页面 BSOD + RGBtrue 仅恢复为未保存草稿，真实配置仍 RGBfalse，未改变用户真实 Hook 信任。用户此前已自行信任插件、确认 work 动画实屏正确，之前“待用户启用/未验收work”的历史条目不再代表当前状态。

Mac 无可用实机：共同 Python/Web 与打包入口已实现，原生组件的规格和质量审查仍在最后复核。Caps LED 回传不在上游公共客户端 API 中，需要真实 HID 描述符验证；共享驱动版本冲突明确拒绝覆盖。后续最高价值验证是在签名 Mac .app 上做授权、按键透传、Fn/Globe、断线/退出释放测试；没有该证据不能关闭双平台完整验收。


2026-09-06 原生源码最终复核：有界规格复核和独立质量审查通过。修复权限/退出释放、所有权与 readiness 分离、未确认销毁时关闭客户端、错误后重新启用、IPC 总超时；Release/NDEBUG 下两个可移植测试仍实际执行并通过。完整 Mac 规格和实机验收未通过，Caps LED 与共享驱动升级缺口保持明确记录。此次本地保存和 Windows 0.2.0 打包不代表双平台任务全部完成；下一步需要真实 Mac 签名构建与设备验收。


2026-09-06 Windows 桌面化 Slice：用户要求独立 Windows app，不再以浏览器作为默认界面。TaskStartSnapshot=main/6edc80c，Git干净，0.2.0后台PID96384运行，用户数据位于windows/data。改动必要性：现启动入口仅webbrowser.open，不能满足桌面窗口使用方式。沿用同一业务/HTTP协议，默认Windows使用pywebview/WebView2原生窗口，保留--no-browser作为无窗口验收入口；新增--browser仅显式兼容旧Web用法。关闭窗口/页面退出/启动失败都必须回收服务、恢复RGB并释放互斥。界面沿用现有资源，新增桌面布局。文件范围desktop.py、__main__.py、web、依赖/打包、tests、README/ADR；Mac输入和键盘协议不变。TDD off，实施后运行生命周期mock、真实桌面EXE窗口/关闭、冻结Hook隔离验收。产物0.3.0，默认启动独立桌面窗口，不自动回退浏览器。

2026-09-06 0.3.0 桌面化交付检查点：pywebview/WebView2 独立窗口、原版 Keyphore 图标、窗口布局、原生保存对话框与重复启动激活已实现。有界独立源码复核通过；84 项 Python 测试中 83 通过、1 项可选真实测试跳过，Node 回归通过；真实 Windows 会话的 Verify-Desktop.py 渲染/设置/导出/API退出通过，Verify-DesktopPackage.py 发布EXE窗口/单实例/WM_CLOSE通过，Verify-Package.py冻结Hook真实隔离生命周期通过。用户旧程序已正常退出，0.3.0桌面EXE启动PID99560，原生窗口标题Keyphore · Keydous、health0.3.0、Responding=True。工作区新增 Keyphore Keydous.lnk，沿用 windows/data；未更改真实Hook信任。只读检查当前用户配置pet=bsod-35b2815c、rgb=false，未覆盖用户保存的配置。桌面化范围完成；Mac实机、原生动态屏幕和其他型号仍按acceptance.md记录，不宣称完成。
