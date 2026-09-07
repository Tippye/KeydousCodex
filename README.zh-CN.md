# Keydous Codex Bridge

[English](README.md) · [Windows 使用指南](windows/README.md)

本项目 **fork 自 [BarryBarrywu/Keyphore](https://github.com/BarryBarrywu/Keyphore)**，基于上游提交 [`9ca11f275809ebc2649bf365effdee8cc7682084`](https://github.com/BarryBarrywu/Keyphore/tree/9ca11f275809ebc2649bf365effdee8cc7682084)。原项目在 macOS 上将 Codex 任务状态转换为 NuPhy 键盘灯光；本 fork 增加了 **Windows + Keydous（键斗士）NJ98 USB 有线连接**的桌面适配，提供状态灯、旋钮快捷操作、改键和手动屏幕上传。

这是独立的第三方项目，不是 Keydous、NuPhy 或 OpenAI 官方产品。保留上游作者署名及 GPL-3.0-only 许可。

## 当前功能

| 功能 | 支持范围 |
| --- | --- |
| Codex 状态 | 通过本地 Hook 聚合执行中、等待审批和一轮结束等事件。 |
| RGB 灯光 | 可选状态联动，写入间隔至少 10 秒，支持恢复原灯光配置。 |
| 旋钮快捷操作 | 左右转切换 Codex 任务或标签；按下唤起 Codex，已在前台时则最小化到任务栏。 |
| 键位映射 | NJ98 普通层和 Fn 层改键，保存原配置并校验恢复结果。 |
| 屏幕内容 | 宠物预览、动画导出，以及手动上传快照或动画到指定 GIF 槽位。 |

## 屏幕无法与 Codex 实时同步

**受当前 Keydous NJ98 屏幕上传方式和刷新速度限制，本项目无法让键盘屏幕与 Codex 状态实时同步。** 图像／动画数据传输和写入耗时，不适合频繁刷新；目前也没有验证到可用的实时画面接口或预加载动画自动切页接口。

上传后的动画可以在键盘上播放，但不会随 Codex 开始工作、等待回应或结束而自动切换。上传画面中的状态标签、锁定键、连接和电量信息只反映生成时刻。本程序因此保留手动上传，不会在每次 Codex 事件发生时重传动画。

这里的限制针对**键盘屏幕内容**。桌面状态显示、可选 RGB 灯光联动和旋钮快捷操作仍可使用。当前没有统一的屏幕刷新率或上传耗时实测值，不能将这一结论推广到其他型号或品牌。

## 开始使用

当前 Windows 版本为 **0.3.2**，需要 Windows 10/11、WebView2 Runtime、正在运行的 Keydous IoT 驱动，以及 USB 有线连接的 NJ98。支持的精确身份为驱动型号 ID `1021`、VID/PID `3151:4015`。

安装、Hook 接入、旋钮设置、配置恢复和构建方式见 [Windows 使用指南](windows/README.md)。本地发布包生成在 `windows/release/`，完整解压 Windows ZIP 后运行 `KeydousCodex.exe`，请保留同目录的配套文件。

[`macos/`](macos/README.md) 中的 Keydous Mac 适配仍为实验性源码，尚无完整的 Mac 编译、签名及实机验收。仓库保留了原 NuPhy 实现；上游的支持范围不代表本 fork 的 Keydous 适配已经验证。

## 其他品牌用户可以自行尝试适配

包括 Keychron 在内的其他品牌用户，可以继续 fork 本项目，让 ChatGPT／Codex 协助修改。请提供准确型号、连接方式、USB 标识，以及官方驱动、SDK 或协议资料。灯光、屏幕和旋钮属于不同能力，需要分别验证；只修改型号允许列表不能完成适配。

可以从这样的提示开始：

> 请把这个 Keyphore fork 适配到我的 [品牌／型号] 键盘，连接方式为 [USB／其他]。先检查官方驱动或 SDK 和设备身份，复用 Codex 状态逻辑，再实现设备支持的灯光、旋钮和屏幕功能。请先测量屏幕更新耗时，再判断能否实时同步，并保存原配置、验证恢复。

代码入口是 [`models.py`](windows/keydous_bridge/models.py)、[`iot.py`](windows/keydous_bridge/iot.py) 和[协议研究](windows/docs/protocol-research.md)。其他键盘可能具备更合适的屏幕接口，但需要在对应设备上确认。

## 项目结构

| 路径 | 用途 |
| --- | --- |
| `windows/` | 共用 Python 应用、Windows 桌面入口、界面、测试及打包。 |
| `macos/` | 实验性的 Keydous macOS 原生输入组件。 |
| `app/`、`runtime/`、`src/`、`plugin/` | 保留的上游 Swift／Rust NuPhy 实现。 |
| `tests/` | 上游测试及夹具；Windows Hook 测试仍复用其中的对照数据。 |
| `docs/adr/` | 架构决策，含 [Keydous 适配边界](docs/adr/0009-add-windows-keydous-port.md)。 |

项目约定见 [AGENTS.md](AGENTS.md)，实现边界见[设计文档](windows/DESIGN.md)，已测与未测范围见[验收记录](windows/docs/acceptance.md)。

## 许可与致谢

感谢 Barry Barry Wu 的 Keyphore 原项目。第一方代码沿用 [GPL-3.0-only](LICENSE)；分发二进制时应保留版权和许可声明，并提供对应源码。第三方声明见 [`LICENSES/`](LICENSES)、[Windows 声明](windows/THIRD_PARTY_NOTICES.md)及 [macOS 声明](macos/THIRD_PARTY_NOTICES.md)。Codex 宠物资源由用户在本机导入，发布包不附带这些资源。
