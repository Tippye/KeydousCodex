# macOS Fn component third-party notices

The native helper compiles the client headers from
`Karabiner-DriverKit-VirtualHIDDevice` commit
`bdfcb459b2eaca8ccda680a73b0dc898f330f4bb` and distributes its unmodified,
upstream-signed 8.5.0 installer package. The upstream project is dedicated to
the public domain under the Unlicense. Its client headers and the Asio headers
they include carry the Boost Software License 1.0. The pinned source tree's
vendored headers retain their original copyright and license comments.

Applicable bundled dependencies include Asio (Copyright 2003-2026 Christopher
M. Kohlhoff, Boost Software License 1.0), Microsoft GSL (Copyright 2015-2026
Microsoft Corporation, MIT), type_safe (Copyright 2016-2020 Jonathan Müller,
MIT), nod (MIT), and pqrs dispatcher, HID, GSL wrapper, and Unix-domain-stream
headers (Copyright Takayama Fumihiko, Boost Software License 1.0).

Packaging preserves the upstream `LICENSE.md`, full Boost/MIT terms, and the
exact scoped pinned header sources beside this notice. The
Keydous build does not rebuild, rename, or claim a signing entitlement for the
DriverKit extension.
