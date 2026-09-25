# Credits and Licensing

The toolkit remains GPLv3. These are separate components, not a blanket MIT
relicensing of the toolkit or its export plugin.

## Native AAC Import

[resolve-aacfix](https://github.com/josephg/resolve-aacfix), by **Seph Gentle
(josephg)**, copyright 2026. Its own code is MIT-licensed. The complete notice is
preserved in [resolve-aacfix-MIT.txt](../native-aac/licenses/resolve-aacfix-MIT.txt).
The toolkit downloads the unmodified, pinned v0.1.1 release directly from the
author and verifies its archive SHA-256 before extraction or execution.
The complete upstream LICENSE, THIRD-PARTY.md, build recipes and notices remain
in the downloaded package. No modified Resolve executable is redistributed.

The upstream release also includes separately licensed components:

- FFmpeg 6.0.1, LGPL-2.1-or-later, with the AV3A demuxer backport by Shuai Liu.
- e9patch/E9Tool by Gregory J. Duck et al., GPL-3.0; its trampoline helper has
  an explicit MIT exception.
- Capstone, BSD-3-Clause; pyelftools, public domain.

Exact source revisions and build information:
[upstream THIRD-PARTY.md](https://github.com/josephg/resolve-aacfix/blob/v0.1.1/THIRD-PARTY.md).
These binaries are downloaded on request, not included in toolkit RPMs or tarballs.

## Native AAC Export

[davinci-linux-aac-codec](https://github.com/Toxblh/davinci-linux-aac-codec), by
**Toxblh**, GPLv3 as declared in its README. The toolkit's experimental export
adapter is derived from this encoder and the included Blackmagic Codec Plugin
SDK example wrappers. Corresponding modified sources and GPLv3 license text
ship in `native-aac/`; the plugin is built locally against matching FFmpeg 6
headers. It is not an export feature provided or endorsed by resolve-aacfix.
The original Resolve-20 plugin remains a separate Legacy download.

## Interface Icon

The info icon is from [Lucide](https://github.com/lucide-icons/lucide), derived
from Feather by Cole Bemis. ISC and MIT notices are retained alongside the
vendored icon in `scripts/resolve_aac_icons.py`.

## Scope

MIT permits use, modification and redistribution with the copyright and license
notice retained. GPL/LGPL components retain their respective obligations.
Credits alone do not replace license notices or source obligations. Neither
MIT nor GPL grants rights to DaVinci Resolve itself or resolves codec patent
licensing. Users must assess applicable Resolve terms and codec licensing for
their use and jurisdiction. This is not legal advice or Blackmagic endorsement.
