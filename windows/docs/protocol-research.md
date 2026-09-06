# NJ98 official frontend protocol research

Research date: 2026-09-06. Static local analysis only; no hardware command was sent by this research task. This is an implementation reference, not evidence that a screen upload, native overlay, persistent storage, or RGB restore has been validated on hardware.

Source: official frontend cache `C:\Users\Payne\AppData\Local\Temp\keydous-main_d787f8ef.js`, 18,605,567 bytes, SHA-256 `f37fee1e406bf19bff3ddbfd664582b8991e9f4d81bfeed83503121a5d79fd04`. All offsets below are **zero-based Python Unicode character offsets in UTF-8-decoded source**, not file-byte offsets or JavaScript UTF-16 offsets. Decoded length: 18,272,452 characters. Small named snippets identify the evidence without vendoring the bundle.

## Identification and scope

- At 2,295,771: ID 1021, VID 12625 / `0x3151`, PID 16405 / `0x4015`, usage 2, usage page 65535, `yc500_nj98_soc`, NJ98, 65-byte feature report configuration, `otherSetting:Zu`.
- At 2,295,545: same model name has a separate entry, ID -2147484669 and PID 16401 / `0x4011`. This is not sufficient evidence to enable wireless writes.
- `Zu` at 1,643,691: screen `isRgb:"16", kbW:160, kbH:80, size:2, date:true, sevenOrEight:16, layer:["1","2","3","4","5"]`.
- Device factory at 13,727,190 maps that exact model name to `QHe`. `QHe` at 10,213,876 extends `zHe`, overriding matrices and common-color lookup only. `zHe` at 10,168,714 extends `jB` (end at 10,209,756). `jB` starts at 7,917,332. Thus the screen overrides in `zHe` and light settings in `jB` are relevant; similarly named classes elsewhere are not automatically relevant.

## Local driver transport

Client construction at 1,608,591 uses `http://127.0.0.1:3814`. The methods are gRPC-Web `/driver.DriverGrpc/sendMsg` and `/driver.DriverGrpc/readMsg` (descriptor around 1,591,607). Do not confuse these with `sendRawFeature` / `readRawFeature` used by other paths.

`SendMsg` serialization at 1,422,699: field 1 string devicepath, field 2 bytes msg, field 3 enum checksumtype, field 4 enum dangledevtype. `ReadMsg` at 1,424,793: field 1 devicepath. `ResRead` at 1,420,866: field 1 err, field 2 bytes msg. Successful send means an empty response err; successful read means empty err, then use msg bytes (`Zn` at 1,608,636; `Qn` at 1,608,998).

Checksum enum at approximately 1,448,400: `BIT7=0`, `BIT8=1`, `NONE=2`. The frontend sends the enum to the installed driver. Do not invent a checksum algorithm or prepend a HID report ID in the bridge. The ordinary device has dangledevtype 0; dongle routing is a separate capability.

Feature wrapper at 7,741,573: default checksum NONE; optional delay defaults to 10 ms. `readFeatureCmd` at 7,742,576 delays before calling readMsg (default 5 ms). `commomFeature` at 7,743,028 performs write then read and supports explicit checksum/delays. Access must be serialized across the complete write/read exchange; merely serializing individual HTTP requests is insufficient.

## Screen image data and rectangles

`Usn` at 16,015,748 computes a bounding box of pixels whose packed RGB value is nonzero. Its `right` and `bottom` are **exclusive**. Black margins therefore shrink the transfer rectangle. This is a bandwidth/storage crop in the official image flow; it is not proof that pixels outside the rectangle or native status widgets remain visible.

`wp` at 2,683,935 converts `(r,g,b)` to `(r >> 3) << 11 | (g >> 2) << 5 | (b >> 3)`. `ofn` at 16,026,998 first crops, then transposes row data: **x is the outer iteration, y the inner iteration**. Each RGB565 value is emitted high byte then low byte. This is column-major RGB565 big-endian; row-major bytes or little-endian pixels would be wrong.

For GIFs the official flow first unions the bounding boxes of all frames, then encodes every frame with that same rectangle (16,100,000–16,101,400). This keeps every frame's encoded byte length equal. No per-pixel alpha field is transmitted. In the all-black edge case, the official crop is zero-sized but its encoder falls back to a full image of zero bytes; do not assume this ambiguous behavior is a validated way to clear the screen.

## Upload preparation is a write

`zHe.getTFTLCDDataRGBImg` at 10,177,694 sends a 19-byte preparation message, then reads readiness. For NJ98 command 0 is `0xA5` (GETTFTLCDDATA constant at 7,764,259). Despite its name it is not an image readback API.

| Byte | Meaning |
| --- | --- |
| 0 | `0xA5` for 16-bit images |
| 1 | currentFrame (static picture slot, or initial GIF frame 0) |
| 2 | frameNum |
| 3 | frameDelay |
| 4, 5 | encoded per-frame byte length bits 0–15, little-endian |
| 6 | 0 |
| 7 | zero-initialized; checksum handling belongs to driver |
| 8, 9, 10, 11 | low bytes of left, top, right, bottom |
| 12, 13, 14, 15 | high bytes of left, top, right, bottom |
| 16, 17 | encoded per-frame byte length bits 16–31, little-endian |
| 18 | GIF layer argument, default 0 |

Preparation calls `writeFeatureCmd(message, 0)` (BIT7), then `readFeatureCmd(100)`. Response byte 1 equal to 1 means ready; byte 1 equal to 0 leads to a 100 ms delay and another preparation exchange. Official source nominally limits busy retries to 10 but its condition `undefined || (byte1 == 0 && retries < 10)` permits unbounded retries when reads stay undefined. A bridge should use a hard overall deadline, bounded attempts, minimum response length, and command-response matching; do not copy that loop bug.

## Frame blocks and slots

`zHe.setTFTLCDDataRGBImg` at 10,178,830 sends `ceil(length / 56)` messages. Each message has an 8-byte header followed by 56 payload bytes, with the last payload zero-padded:

| Byte | Meaning |
| --- | --- |
| 0 | `0x25` (SETTFTLCDDATA, constant at 7,764,222) |
| 1 | currentFrame |
| 2 | frameNum |
| 3 | frameDelay |
| 4, 5 | block index, little-endian uint16 |
| 6 | actual unpadded payload length, 1–56 |
| 7 | zero-initialized; BIT7 checksum delegated to driver |
| 8–63 | payload |

The official method sleeps 3 ms before each block and sends through `Zn(devAddr.toString(), block, BIT7, dangleType)`. It aborts on failed send. There is no final device-level image checksum/readback in this method; successful HTTP writes alone do not establish correct physical display.

Static PNG flow at 16,103,757: `frameNum=1`, `currentFrame=picLayer`, `frameDelay=0`; preparation defaults byte 18 to 0. After readiness wait 100 ms, send frame blocks, then wait 500 ms. The UI offers five static slots 1–5 and subtracts one for protocol values (16,087,090; 17,249,431).

GIF flow at 16,101,483: initial preparation only on frame 0 with `gifLayer`; every frame gets `currentFrame=0..N-1`, `frameNum=N`, shared delay and bounds. Wait 100 ms after readiness and 500 ms after the last frame. UI offers three animation slots for a model name containing `nj98` (17,248,400–17,249,881), again subtracting one. This string-based UI rule is not suitable hardware capability detection. Delay UI is 1–255 ms (17,249,881); generated preview clamps its playback delay to at least 20 ms, while upload passes the stored delay byte.

`getFramesMax` at 16,091,534 uses memory sizing, 4096-byte pages, `sevenOrEight` MiB, reserves five static images and divides remaining frame capacity by three for NJ98. For 160×80×2 and the NJ98 value 16, it yields 193 frames per animation slot, capped at 250 globally. This is strong evidence for a stored-resource upload path. It is not direct proof of a particular Flash controller's write behavior or endurance.

The GIF uploader also pauses the driver's wireless polling loop through `changeWirelessLoopStatus` (helper `eo` around 1,610,440) and resumes it afterwards. An implementation using that operation needs `finally` restoration. The surrounding UI stops/restarts background light work during upload. Avoid concurrent official-web and bridge transfers.

## Native overlay, persistent storage, and live updates

No relevant frontend call has been found that replaces the built-in default cat while guaranteeing native Num/Caps, mode, and battery widgets remain visible. No RAM framebuffer streaming mode or low-cost software selection of a preloaded NJ98 image slot has been established. The slot argument is part of upload metadata, not evidence of a display-page switch.

The source includes screen Flash erase (`jB.setFlashChipErase`, 7,943,625; command `0xAC`) and a warning-bearing UI around 17,240,000. That is a destructive maintenance path, not an upload prerequisite and not a recovery action for this bridge. Firmware/bootloader paths are similarly out of scope. Do not invoke them. The image memory/page accounting and storage slots justify treating upload as potentially persistent; event-driven GIF rewrites and repeated status-frame uploads remain disabled until memory behavior is established.

## Follow-up: preloaded animation switching (2026-09-06)

The user reports that an uploaded work-state animation now displays correctly on the physical
screen. This supersedes the earlier untested-upload status for that one case; the slot number,
firmware version and transfer duration were not supplied. It does not establish automatic slot
selection, retention across power cycles or native overlay coexistence.

A second static inspection of the same official bundle (SHA-256 rechecked and unchanged) traced
the NJ98 `QHe -> zHe -> jB` methods, upload UI state and driver calls. No independent playback-slot
selector was found in these paths. Candidate names were resolved as follows (offset convention
is the same as above):

| Candidate | Evidence and conclusion |
| --- | --- |
| `setGifLayer` / `gifLayer` | At 16,087,188 the setter only assigns frontend state. At 17,249,881 the dropdown calls that setter. At 16,101,510 the value is consumed by upload preparation. Selecting a dropdown value does not itself send a playback command. |
| `SetLight.screenId` / `setScreenIndex` | `startLight` around 15,962,130 passes `screenStore.screenIndex` to the driver's SCREEN lighting mode. `getScreenArr` at 16,300,474 enumerates Electron desktop-capture sources; the index identifies a computer display for lighting follow, not a keyboard GIF slot. |
| `setScreen` | The inherited implementation at 7,922,694 sends color data via `FEA_CMD_SET_WINDOS`; its caller at 15,965,821 is part of the screen-color lighting flow. It is not a TFT animation selector. |
| `getOledEffect` / `setOledEffect` | Implementations at 10,201,350 / 10,203,543 expose effect types, brightness, speed and RGB, with no GIF slot parameter. The store getter at 15,951,498 requires `otherSetting.screenLight`; NJ98's `Zu` options at 1,643,691 expose `LED` upload settings, but no `screenLight`. Their names do not establish an NJ98 playback API. |
| `setUserGifStart` | At 10,176,636 this has no slot argument. The caller around 16,897,420 invokes it before a loop sending per-key RGB frames under `LightUserColor`: this is custom animated backlight upload, not switching a stored TFT animation. |
| `getKeyboardOption` / `setKeyboardOption` | At 7,919,235 / 7,918,481 the exposed fields concern locks, system, lighting, key layers and power saving. No playback-slot field is parsed or written. |
| `FEA_CMD_SET_OLEDOPTION` | Its relevant use around 7,940,471 is inside `setOLEDSysInfo` and sends system telemetry; the name alone is not evidence of page selection. |

Conclusion: the existing official frontend/IoT paths examined do not provide enough evidence to
implement “preload three animations, then switch on Codex state changes.” This is a bounded
negative result, not proof that firmware has no undocumented capability. No experimental hardware
commands were sent, and runtime capabilities remain unchanged. The next useful evidence would be
an exact-model vendor command/API for selecting and reading the active slot, or an official UI
action demonstrably switching already stored animations without uploading. Any candidate then
needs a recoverable physical switch-and-restore check and clarification of whether switching
writes persistent configuration. Physical Fn+Delete cycling alone would not establish a host API
or deterministic selection of a named slot.

## Current-device read-only capability inspection (2026-09-06)

Scope: live NJ98 USB queries through the official IoT service, Windows HID descriptor inspection,
and static analysis of the previously identified official frontend. This is not a firmware-image
disassembly or an exhaustive enumeration of undocumented commands. No firmware image was obtained.
All device queries were known read operations, serialized under the existing `HardwareOwner`
mutex after matching exactly one online ID 1021 / VID 0x3151 / PID 0x4015 / USB device.
No settings, animation resources, firmware or boot modes were changed. The bridge HTTP status
request timed out, but the hardware mutex was available during each live inspection.

### Live identity, versions and interface

- Model: NJ98, `yc500_nj98_soc`, wired USB, ID 1021, VID/PID 3151:4015. Driver battery field absent.
- Keyboard firmware: response bytes `[0x45, 0x01]`, integer 0x0145. The official frontend uses
  `toString(16)` at approximately 15,889,772, so its version label is **145**, not decimal 325 or
  an inferred dotted version.
- Screen firmware: bytes `[0x27, 0x01]`, integer 0x0127, official label **127**. The field called
  `flashVersion` returned zero; this is not a RAM/Flash capacity measurement or proof of no Flash.
- Windows `HidD_GetPreparsedData` / `HidP_GetCaps` on the exact device path used by IoT returned
  UsagePage 65535, Usage 2, InputReportByteLength 0, OutputReportByteLength 0,
  FeatureReportByteLength 65, NumberFeatureDataIndices 1, NumberOutputDataIndices 0.
  The metadata handle used requested access 0 and was closed after reading. This inspects the
  selected vendor control collection, not every interface on the composite USB device.
- The 65-byte length includes the report-ID position, per
  [Microsoft HIDP_CAPS documentation](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/hidpi/ns-hidpi-_hidp_caps).
  There is no declared Output Report route on this collection. A direct USB implementation cannot
  simply substitute a high-throughput Output Report stream on this same interface. Feature-report
  throughput and other interfaces were not benchmarked or exhaustively inspected.

### Read results

Each of the nine single-report queries returned 64 bytes with a matching command byte. Prefixes
below are the first eight response bytes in hex; they are sufficient for the cited scalar fields.
The sleep response additionally had byte 8 equal to 0x46. Reads establish response behavior, not
validation of their corresponding setters or every possible parameter value.

| Query | Response prefix | Observation |
| --- | --- | --- |
| Keyboard version 0x80 | `80 45 01 00 00 00 00 7f` | Official label 145 |
| Screen version 0xAD | `ad 27 01 00 00 00 00 00` | Official label 127; flashVersion field 0 |
| Current profile 0x85 | `85 00 00 00 00 00 00 7a` | Selector 0; no evidence of additional supported profiles |
| Keyboard options 0x86 | `86 00 02 00 00 00 00 79` | Raw option bytes 2, 0, 0, 0; preserve bit meanings from the official getter |
| Report rate, profile 0, 0x84 | `84 00 01 00 00 00 00 7b` | Official decode: 1000 Hz keyboard reporting, not screen upload throughput |
| Main RGB 0x87 | `87 42 08 ff 00 00 00 00` | Original seven bytes `[66,8,255,0,0,0,0]` |
| Automatic OS detection 0x97 | `97 00 00 00 00 00 00 68` | False under the official boolean decoder |
| Debounce 0x91 | `91 00 00 00 00 00 00 6e` | Raw field 0; NJ98's options do not declare the debounce UI, so this does not validate adjustable debounce |
| Sleep 0x92 | `92 2c 01 2c 01 50 46 50` | Raw BT/2.4G sleep values 300, 300; raw deep-sleep values 18000, 18000. UI normalization is separate. |

Normal and Fn bank 0 were each read using the existing eight-block reader: 512 bytes per bank,
16 additional command/read exchanges. Normal-bank SHA-256:
`74ec476c089948e7b3f662acf74deacd07f9526bcb820e3a13e22cda66b1029a`;
Fn-bank SHA-256: `f3bdd3f9f2a4bd98dcec51457fbdb137634c4b22fe567248caef5595530eb613`.
No individual user mappings or macro contents were exported. Matrix framing follows the official
raw-block parser, which does not require echoed command headers in those data blocks.

### Operation inventory and confidence

| Operation family | Evidence / current limit |
| --- | --- |
| Identify device, read keyboard/screen version | Live responses above |
| Read normal/Fn key assignments | Live complete-bank reads above |
| Read RGB, profile, report rate, keyboard options, auto-OS, sleep | Live responses above |
| Upload and play a work-state screen animation | User's physical-display confirmation; not repeated during this inspection |
| Write and restore main RGB | Earlier physical write/readback/restoration evidence in this document; not repeated here |
| Remap keys and Fn actions; macro storage; custom backlighting | Concrete inherited implementations in the official model path; no write acceptance performed in this inspection |
| Change report rate, locks/system options, sleep and auto-OS | Official implementations plus matching getters; setters not exercised here |
| Upload static screen images / other GIF resources | Official transfer paths and slot definitions; static images and all slots not individually accepted here |
| Screen clock synchronization | `Zu.LED.date=true`, `startDate` around 15,947,396 calls `setOLEDClock`; `jB.setOLEDClock` at 7,938,843 implements the write. Source-supported, not exercised here. |
| Weather/system telemetry, screen effects, magnetic-switch functions | Methods exist in shared classes, but NJ98 lacks the relevant `weather`, `isInfro`, `screenLight` or `magnetism` declarations. Do not claim these as NJ98 capabilities based on method names. |
| Reset and firmware/resource maintenance | Official shared paths exist; not executed or certified by this inspection |
| Free-RAM query, volatile resource upload, resource-ID selection, independently refreshed tag layer | No established API in the inspected paths; neither RAM size nor firmware impossibility has been established |

The live device now establishes the version pair needed for any subsequent exact-firmware study.
It still does not justify advertising RAM animation caching, software GIF switching, native
overlay composition or live framebuffer streaming. Those require additional protocol/firmware
evidence and targeted physical validation.

## Keyboard RGB settings (separate from screen RGB565)

Relevant inherited implementation: `jB.setLightSetting` 7,931,250 and `jB.getLightSetting` 7,934,812; NJ98 changes the common-color lookup in `QHe` (10,214,508). Complete inheritance is `QHe → zHe → jB → oB → WD → jD → mD → QF → TF → nF`. Final NJ98 constants are `SET_LEDPARAM=0x07` at 7,830,298 and `GET_LEDPARAM=0x87` at 7,830,333, overridden by `mD`. **Do not use generic base values 0x04/0x84: on NJ98 these control report rate.** `MAXSPEED=4`, `DAZZLE=8`, `NORMAL=7` from `jB`.

Read: 64 zero-initialized bytes with byte 0 `0x87`, `commomFeature(request, BIT7)`. Response positions: byte 1 effect, byte 2 stored speed (`logicalSpeed=4-byte2`), byte 3 brightness, byte 4 option/color selector, bytes 5–7 RGB. For ordinary color modes low nibble 8 means dazzle and 7 means custom RGB; other low-nibble values use NJ98 COMMONCOLOR: 0 white, 1 red, 2 orange `0xFF5500`, 3 yellow, 4 green, 5 cyan `0x55FFFF`, 6 blue, 7 purple `0x5500FF`. Note selector 7 is also NORMAL and is treated as custom by the base method. Packed `0xFAFAFA` is mapped back to white `0xFFFFFF`.

Write: 64 zero-initialized bytes, byte 0 `0x07`; byte 1 effect; byte 2 `4-speed`; byte 3 brightness; byte 4 selector/options; bytes 5–7 RGB. The official write uses `writeFeatureCmd(message, BIT8, 500)` and then waits COMMONDELAY 500 ms. For solid color: effect 1, speed input 0 (stored byte 2 = 4), byte 4 = 7 for custom RGB or 8 for dazzle. White is deliberately sent as `0xFAFAFA`, not `0xFFFFFF`.

Effect IDs in this class: off 0, always-on 1, breath 2, neon 3, wave 4, ripple 5, raindrop 6, snake 7, press-action 8, convergence 9, sine 10, kaleidoscope 11, line-wave 12, user-picture 13, laser 14, circle-wave 15, dazzling 16, rain-down 17, meteor 18, press-action-off 19, music 20, screen-color-follow 21, alternate music 22, train 23, fireworks 24, user-color 66. The high nibble of byte 4 is effect-specific, so restoration should preserve the original raw configuration rather than map every effect through a lossy UI object.

Real NJ98 RGB validation on 2026-09-06 passed using the final constants: original seven bytes `[66,8,255,0,0,0,0]`, working write/readback `[1,4,2,7,58,189,231]`, restored/readback `[66,8,255,0,0,0,0]`. RGB writes have no proven volatile flag; do not describe them as RAM-only. Default RGB linkage off; enable only with reliable original-state capture, serial writes, conservative rate limiting and explicit recoverable state. Normal-exit restoration is implementable; guaranteed restoration after a crash is not established.

The initial experiment incorrectly used the generic constants. It was stopped and audited: active profile was 0; report-rate reads for profiles 0 and 1 both returned code 1 (1000 Hz), with no observed 250 Hz result in profile 1. No unknown prior profile value was guessed or written during that audit. The regression suite now asserts the final RGB command bytes explicitly. Earlier static protocol reviews did not catch this inheritance error and are not hardware acceptance evidence.

The official store additionally checks powerSaveMode before lighting changes and calls `setLightType(OTHER=2)` to stop driver-managed music/screen streaming. The current bridge does not own those driver streaming modes: do not run the official web controller concurrently with bridge writes. No extra driver mode transition was needed for the validated NJ98 RGB operation. Screen constants `0xA5/0x25` remain unchanged through the complete inheritance chain.

## Adapter expansion recommendation

Initial write allowlist should be **only** the current exact ID 1021 + VID/PID + model/protocol family, and only after a reviewed first upload. Rendering/export can be available before hardware validation. Unknown IDs remain read-only even when VID/PID match.

| Official entry | Evidence offset | Suggested status |
| --- | --- | --- |
| NJ98 `yc500_nj98_soc`, ID 1021, PID 16405 | 2,295,771 | Primary adapter; user reports work-animation display success on 2026-09-06; automatic slot selection remains unverified |
| NJ98 wireless-family entry ID -2147484669, PID 16401 | 2,295,545 | Recognize separately; no wireless upload enablement |
| NJ98 CP `yc3121_nj98_megnatism`, ID 1259; UK ID 1688 | 2,236,498; 2,116,908 | Same screen dimensions/config references; separate protocol inheritance/firmware verification before writes |
| NJ98 CP 1030 `yc3121_nj98_1030_megnatism`, ID 1863 | 2,076,560 | Separate adapter verification |
| NJ98 EP regional `yc3121_nj98ep_uk*`, IDs 2000–2004 | 2,041,796–2,043,895 | Separate adapter verification; config Ju has different memory metadata |
| NJ98-V2 `yc3123_nj98_soc`, ID 2956, PID 20482 | 2,503,561 | Different group/protocol family; do not route through QHe |
| NJ98-V2-D `yc3123_qn_nj98_v2_d_3m_1k`, ID 3873, PID 20482 | 2,502,210 | Different group/protocol family |
| NJ98CP-V3 `ry5088_nj98cp_8k_8k`, ID 2576, PID 20527 | 2,538,964 | Different group/protocol family |
| NJ98-CP V4 `ry5088_qn_nj98_cp_v4`, ID 3496, PID 20528 | 2,502,744 | Different group/protocol family |

Track identified / exportable / upload validated / overlay validated / live-state validated independently. This static research establishes packet construction and crop/slot semantics, while leaving native overlay coexistence and memory behavior unresolved.
