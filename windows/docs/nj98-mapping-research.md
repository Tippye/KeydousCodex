# NJ98 mapping and native screen capability research

2026-09-06. Static analysis of the same official frontend bundle identified in `protocol-research.md`; no hardware commands, discovery probes, writes, or runtime execution of the bundle were performed. **Source-derived, not hardware-validated.** All source offsets are zero-based Python Unicode character offsets in UTF-8-decoded text. Source SHA-256: `f37fee1e406bf19bff3ddbfd664582b8991e9f4d81bfeed83503121a5d79fd04`.

## Exact model, inheritance, and supported banks

The entry at 2,295,771 is ID 1021, VID 12625 / 0x3151, PID 16405 / 0x4015, `yc500_nj98_soc`. Factory 13,727,190 selects `QHe`. The full chain is **QHe → zHe → jB → oB → WD → jD → mD → QF → TF → nF**. Do not select methods/constants merely by the closest generic class name.

The descriptor has `fnLayer:1`, with no `layer`, `profileLayer`, or `fnSysLayer`. Helpers `c0t` (11,906,984), `f0t` (11,907,297), `h0t` (11,907,420), and `m0t` (11,907,538) default this to **one normal bank, selector 0; one Fn bank, selector 0; no separately declared Mac Fn bank**. Enumeration calls `getFnKeyConfig(X)` for X from 0 to count−1 (15,898,985). A generic command accepting a profile byte is not evidence that profiles 1–255 are supported by this model.

`QHe` assigns `defaultMatrix=IHe` and `defaultFnMatrix=YHe` at 10,214,441 / 10,214,473. `IHe` begins at 10,209,762 and `YHe` at 10,210,899; both contain **512 bytes = 128 four-byte slots**. `defaultMACFnMatrix` remains the empty TF default (7,764,962); there is no override anywhere in the relevant chain. The official store's general Mac Fn machinery is used by other device families and must not be transplanted to NJ98.

## Final mapping commands and transport

Use the local driver's `sendMsg` / `readMsg` transport documented in `protocol-research.md`. A 64-byte packet below is zero-initialized unless specified. BIT7 is driver checksum enum 0, BIT8 is 1, NONE is 2; ordinary dongle type is 0. No HID report ID is prepended by these methods. Serialize a complete exchange and, for matrix reads, all blocks. These mappings are potentially persistent; no volatile flag was found.

| Operation | Final command | Effective implementation / evidence |
| --- | --- | --- |
| Normal matrix read | 0x89 | `jD._getKeyMatrix`, 7,865,587; constant from mD at 7,830,480 |
| Fn matrix read | 0x90 | Literal in `TF._getFnKeyMatrix`, 7,801,407 |
| One normal key write | 0x13 | `zHe.setKeyConfigSimple`, 10,172,569; constant 10,169,281 |
| One Fn key write | 0x15 | `zHe.setFnKeyConfigSimple`, 10,173,298; constant 10,169,463 |
| Bulk normal matrix write | 0x09 | `jB._setKeyConfig`, 7,925,965; constant from mD 7,830,444 |
| Bulk Fn matrix write | 0x10 | Literal in `TF._setFnKeyConfig`, 7,776,016 |
| Active profile read/write | 0x85 / 0x05 | `jD.getCurrentProfile` / `setCurrentProfile`, 7,860,215 / 7,859,785; mD constants 7,830,190 / 7,830,156 |

**Matrix read:** eight exchanges, block numbers 0–7. Request byte 0 is 0x89 (normal) or 0x90 (Fn); byte 1 is the normal profile/Fn selector; byte 2 is the block number. Each exchange is `commomFeature(request, BIT7)`. The methods concatenate the **entire returned buffers**, with no command/header removal. Eight 64-byte responses produce the 512-byte matrix. This is a different framing contract from an echoed command plus 56-byte payload. Response lengths and real driver framing still need validation; do not require response[0] to equal the request command because response[0] is matrix data in the official parser. Abort on absent/short/oversized blocks instead of padding an incomplete backup.

**One-key write:** byte 0 is 0x13 or 0x15; byte 1 selects profile/Fn bank; byte 2 is the zero-based **matrix slot index**; bytes 8–11 are the four-byte action token. Official code calls `writeFeatureCmd(packet, BIT7)`, then `pp()` (2,683,005): on Windows this pauses the wireless loop, waits a default 50 ms, and emits a restart notification; on other platforms it waits 500 ms. No command readback occurs in this method. Preserve the raw 512-byte preimage and verify the target and all untouched slots with a complete read after any future authorized write. The constants `GET_KEYMATRIX_SIMPLE=0x93` and `GET_FN_SIMPLE=0x95` exist in zHe, but no corresponding relevant single-key getter implementation was found; do not invent their response schema.

**Bulk write caveat:** both bulk methods create an eight-byte header `[command, selector, 248, 1, block, 0, 0, checksum]`, append 56 data bytes, and iterate exactly nine blocks. Byte 7 is manually `255 - (sum(bytes 0..6) & 255)`; the send uses the default checksum NONE. Normal write waits 1000 ms afterwards; Fn waits 50 ms. Nine blocks transfer 504 bytes despite a 512-byte default/read matrix. The last eight default bytes are zero, but this does not prove all firmware versions ignore those slots. Do not use this path as a complete raw restore or reconstruct a matrix from only known key assignments.

**Active profile:** read sends 0x85/BIT7 and reads byte 1; write sends 0x05 with byte 1=profile/BIT7 and updates the frontend's cached profile only after send success. Reading a different bank does not require switching the active profile.

## Action encoding and physical identity

`vF` at 7,751,512 translates UI configurations to four-byte action tokens; `fF` at 7,748,850 translates differences against the default matrix back to UI configurations. A raw matrix backup is more authoritative than that lossy diff representation.

| Action | Four-byte token / meaning |
| --- | --- |
| Ordinary keyboard usage | `[0, 0, usage, 0]`; e.g. A `[0,0,4,0]` |
| Combo | `[0, modifierUsage, keyUsage, secondKeyUsage]`; modifier is a usage, **not a HID modifier bitmask** |
| Modifier choices in this UI | `none=0, ctrl=224, shift=225, alt=226, win=227` (`CF`, after 7,801,407) |
| Firmware Fn | `[10,1,0,0]`; packed pseudo-HID `0x0A010000` = 167837696 |
| Media | Consumer usage stored low/high in bytes 2/3, tag 3: mute `[3,0,226,0]`, volume− `[3,0,234,0]`, volume+ `[3,0,233,0]`, calculator `[3,0,146,1]` |
| Macro reference | `[9, mode, macroIndex, 0]`; mode 0 repeat-count, 1 on/off, 2 touch-repeat; macro data is separate |
| Mouse | Tokens from `MF`, e.g. left `[1,0,240,0]`; do not encode as a keyboard usage |
| Disabled/unknown | Decoder recognizes `[0,0,0,0]` or `[0,0,3,0]` as disabled, `[0,0,1,0]` as unknown; retain all raw tokens on round-trip |

`findIndexInDefaultMatrix` (7,787,969) scans four-byte **default** entries. Ordinary keys match `[0,0,hid,0]`; special actions use packed big-endian four-byte values (`Op`, 2,686,757). The optional UI `index` is the occurrence number of an otherwise identical default action, not a slot number. Do not pass a Windows virtual-key code, macOS virtual keycode, visual-array position, or packed special action as byte 2. NJ98's source layout entries each resolve uniquely against IHe.

The source key-name table includes conversions for Windows keycodes/scancodes (around 7,727,000); these are host input helpers, not firmware slot addresses. A portable application should retain matrix slot + raw action, and use an independent host input conversion layer.

### Complete source layout to matrix slot

The layout lookup at 7,088,983 selects `VN` (4,875,035). VN has **101 controls: 98 keys and three knob actions**, not a 96-slot matrix. IHe has 102 nonzero slots: slot 75 `[0,0,50,0]` is not in VN's visible layout. Preserve it and every zero/padding slot. The following HID column is the official UI's numeric usage or packed pseudo-HID; packed values are not standard USB usage IDs.

| Key | Slot | HID / packed | Key | Slot | HID / packed | Key | Slot | HID / packed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Esc | 0 | 41 | F1 | 12 | 58 | F2 | 18 | 59 |
| F3 | 24 | 60 | F4 | 30 | 61 | F5 | 36 | 62 |
| F6 | 42 | 63 | F7 | 48 | 64 | F8 | 54 | 65 |
| F9 | 60 | 66 | F10 | 66 | 67 | F11 | 72 | 68 |
| F12 | 78 | 69 | Delete | 84 | 76 | Calculator | 90 | 50369025 |
| U- | 109 | 50391552 | Mute | 102 | 50389504 | U+ | 110 | 50391296 |
| ` | 1 | 53 | 1 | 7 | 30 | 2 | 13 | 31 |
| 3 | 19 | 32 | 4 | 25 | 33 | 5 | 31 | 34 |
| 6 | 37 | 35 | 7 | 43 | 36 | 8 | 49 | 37 |
| 9 | 55 | 38 | 0 | 61 | 39 | - | 67 | 45 |
| = | 73 | 46 | BackSpace | 79 | 42 | Page Up | 85 | 75 |
| Num Lock | 91 | 83 | num_/ | 97 | 84 | num_* | 103 | 85 |
| num_- | 105 | 86 | Tab | 2 | 43 | Q | 8 | 20 |
| W | 14 | 26 | E | 20 | 8 | R | 26 | 21 |
| T | 32 | 23 | Y | 38 | 28 | U | 44 | 24 |
| I | 50 | 12 | O | 56 | 18 | P | 62 | 19 |
| [ | 68 | 47 | ] | 74 | 48 | \ | 80 | 49 |
| Page Down | 86 | 78 | num_7 | 92 | 95 | num_8 | 98 | 96 |
| num_9 | 104 | 97 | num_+ | 106 | 87 | Caps Lock | 3 | 57 |
| A | 9 | 4 | S | 15 | 22 | D | 21 | 7 |
| F | 27 | 9 | G | 33 | 10 | H | 39 | 11 |
| J | 45 | 13 | K | 51 | 14 | L | 57 | 15 |
| ; | 63 | 51 | ' | 69 | 52 | Enter | 81 | 40 |
| num_4 | 87 | 92 | num_5 | 93 | 93 | num_6 | 99 | 94 |
| Shift | 4 | 225 | Z | 16 | 29 | X | 22 | 27 |
| C | 28 | 6 | V | 34 | 25 | B | 40 | 5 |
| N | 46 | 17 | M | 52 | 16 | , | 58 | 54 |
| . | 64 | 55 | / | 70 | 56 | r_Shift | 76 | 229 |
| ↑ | 82 | 82 | num_1 | 88 | 89 | num_2 | 94 | 90 |
| num_3 | 100 | 91 | num_Enter | 107 | 88 | Ctrl | 5 | 224 |
| Win | 17 | 227 | Alt | 23 | 226 | (space) | 41 | 44 |
| r_Alt | 59 | 230 | FN | 65 | 167837696 | r_Ctrl | 71 | 228 |
| ← | 77 | 80 | ↓ | 83 | 81 | → | 89 | 79 |
| num_0 | 95 | 98 | num_. | 101 | 99 |  |  |  |

## What “Mac Fn” means here

The physical NJ98 Fn key is slot 65, action `[10,1,0,0]`. The bundle's shared action dictionary `MC` (around 7,729,000) labels this `fn`; it is a **firmware layer action**. This proves neither that pressing it sends an input event to the host nor that it produces Apple's Fn/Globe event. No Apple Fn/Globe output encoding for this NJ98 class was established. Mapping another physical key to this token is a firmware-Fn remap, not proven macOS Fn/Globe support.

Examples from the NJ98 default Fn matrix YHe: Fn+F1 is brightness− `[3,0,112,0]`; Fn+F2 brightness+ `[3,0,111,0]`; Fn+F7 previous `[3,0,182,0]`; Fn+F8 play/pause `[3,0,205,0]`; Fn+F9 next `[3,0,181,0]`; Fn+F10 mute `[3,0,226,0]`; Fn+F11 volume−; Fn+F12 volume+. The zero entries in YHe cannot safely be given transparent/fallthrough semantics from source alone: the general decoder calls zeros disabled and the firmware behavior has not been observed. The simple Fn reset path copies the matching four-byte YHe entry when its frontend reset condition is true (10,173,298).

The separate automatic OS option uses zHe commands SET 0x17 / GET 0x97 (10,169,627 / 10,169,669; methods 10,171,810 / 10,172,190). Byte 1 is Boolean; both use BIT7. This does not establish separate Mac mapping storage. `jB.getKeyboardOption` (7,919,234) reads 0x86 per profile and interprets response byte 2 bit 1 as Mac; its setter constructs the system field with `Number(system) << 2`, which is inconsistent with that reader and string-valued UI objects. Preserve raw options; do not implement an OS-mode write by assuming the mismatch is harmless.

For macOS-native Fn/Globe, a separate host-side implementation and macOS acceptance evidence are needed. “One app on Mac/Windows” can share firmware mapping data and UI while keeping native input handling and permissions platform-specific.

## Native cat/status layer and screen limitations

Read `protocol-research.md` for the established stored-image/GIF upload path. Additional source evidence does not resolve native-overlay coexistence:

- `jB.setOLEDClock` (7,938,845) updates clock fields through 0x28; year occupies bytes 8–9 big-endian, followed by month/day/hour/minute/second in 10–14. `setOLEDLanguage` (7,938,468) uses 0x27 with byte 1 inverted Boolean. These are native data/settings paths, not image layering controls.
- `jB.setOLEDSysInfo` (7,939,780) uses **0x22 `SET_OLEDOPTION`** for disk, memory, CPU and network values in bytes 8–21. The generic name “OLEDOPTION” is not evidence of a page-select or overlay bit. It is not a native Num/Caps/battery readback.
- `zHe.getOledEffect` / `setOledEffect` (10,201,349 / 10,203,542) use 0xAB / 0x2B, with effect IDs 64 clock, 65 CPU, 66 USER, 67 WRITEWORD, plus various light effects. Several music/screen-color cases instead change keyboard LEDPARAM. The relevant NJ98 `Zu.LED` UI metadata does not expose these as confirmed NJ98 page switches. These generic inherited methods are insufficient evidence for selecting a particular preloaded NJ98 PNG/GIF slot or replacing the cat under native widgets.
- YHe includes opaque tokens such as slot 84 `[19,0,0,0]`, slot 90 `[19,2,0,0]`, and slots 105/106 `[19,3,1,0]` / `[19,3,0,0]`. They are retained as opaque actions; no verified label or page-selection meaning is assigned.

**Still unproven:** native cat replacement while preserving firmware status widgets; host-visible physical Fn input; Apple's native Fn/Globe event; Mac-specific mapping bank; RAM framebuffer streaming; cheap software selection of a preloaded screen slot; stored-image memory endurance. No bootloader, firmware upgrade, Flash erase, or exploratory packet was sent.

## Acceptance boundary

This document establishes reproducible frontend source traces and the complete visible NJ98 slot lookup only. It does not establish hardware mapping read/write acceptance. Before enabling firmware edits: verify exact device identity, confirm all eight raw matrix blocks and bank selectors, save an intact raw backup, then validate a recoverable single-key change and restoration with both readback and physical input. Keep Fn/Globe and native-overlay capabilities marked unsupported/unverified until independently observed. The previously hardware-validated RGB result in `protocol-research.md` does not validate mapping or screen behavior.
