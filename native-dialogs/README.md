# Native Dialog Bridge

Enabled by **Native KDE file dialogs**. Start Resolve from the toolkit, or from
the toolkit's installed font-fix launcher. Restart Resolve after toggling.

- **Relink Clips / Media in Bin:** the native folder picker passes its choice to
  Resolve's original folder controller. Resolve keeps the clip/bin selection and
  performs the relink itself. Cancellation changes nothing; an unconfirmed folder
  falls back to Resolve's original dialog.
- **Deliver Browse:** launches the existing native save picker before displaying
  Resolve's old window. The last export directory and notification setting are
  retained. This does not start a render or change codecs.

## Compatibility

The private folder layout is guarded by the complete executable SHA-256. The
currently verified build is Linux x86-64 **Resolve Studio 21.1.1.0010 with the
toolkit's Native AAC patch**. The guard hashes the running executable in the
background at startup; it never permits private layout access before verification.
Unknown builds keep their original Relink dialog and the existing Deliver
watcher. A Resolve update or a different patch build can therefore disable this
enhancement until verified; a matching version number alone is insufficient.

Only source is shipped. A C++17 compiler, pkg-config and Qt5 Widgets development
headers build the extension against the installed Resolve Qt libraries on first
launch. The installer offers these dependencies; the RPM requires them. The
compiled library is cached under `$XDG_CACHE_HOME/resolve-aac-tools/native-dialogs`
(normally `~/.cache/resolve-aac-tools/native-dialogs`). Missing dependencies or a
build failure leave the existing dialog route available. Resolve installation
files are not modified. No test logs, media paths or compiled libraries are shipped.

The bridge uses unsupported private Qt layouts only on the verified build.
This is independent of the AAC import/export patch and can be disabled with the
native-dialog toggle. External scripting set to **Local** is still needed for
the Deliver destination helper.
