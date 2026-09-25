# Native AAC Export (Experimental)

GPLv3 encoder derived from [Toxblh's davinci-linux-aac-codec](https://github.com/Toxblh/davinci-linux-aac-codec).
Toolkit modifications include matching FFmpeg 6 headers, ABI checks, end-of-stream
draining, and ADTS packet framing so the MP4 muxer obtains AAC-LC configuration.
SDK wrappers originate from that project and Blackmagic's Codec Plugin example.

The toolkit builds this source locally when installing Native AAC. It links to
the AAC-enabled FFmpeg 6.0.1 libraries from
[Seph Gentle's resolve-aacfix](https://github.com/josephg/resolve-aacfix), MIT for
its own code; see `licenses/resolve-aacfix-MIT.txt` and upstream `THIRD-PARTY.md`.
No Resolve binary or FFmpeg binary is included in the toolkit distribution.

Tested: Fedora, Resolve Studio 21.1.0.0014, five-second H.264 MP4 export with
AAC-LC (48 kHz stereo), 24-bit input; full audio decode succeeds. Long renders,
other containers/versions and precise A/V sync are not yet validated. The last
AAC frame is padded (about 13 ms in that test). 16/24-bit PCM input is advertised;
only 48 kHz stereo is supported. Retain Legacy for production fallback.

The upstream import patch and this export plugin are separate components.
The latter is not an export feature provided or endorsed by resolve-aacfix.
