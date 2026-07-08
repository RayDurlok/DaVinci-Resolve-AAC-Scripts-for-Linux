%global appid    io.github.raydurlok.ResolveAacTools
%global srcname  resolve-aac-tools
%global sharedir %{_datadir}/%{srcname}

Name:           resolve-aac-tools
Version:        0.1.14
Release:        1%{?dist}
Summary:        AAC audio remux tools and system tray for DaVinci Resolve on Linux

# The scripts are GPLv3. Switch to GPL-3.0-only if upstream ever drops "or later".
License:        GPL-3.0-or-later
URL:            https://github.com/RayDurlok/DaVinci-Resolve-AAC-Scripts-for-Linux

Source0:        %{srcname}-%{version}.tar.gz
Source1:        %{appid}.metainfo.xml
Source2:        %{appid}.desktop
Source3:        resolve-aac-import.desktop
Source4:        resolve-aac-start.desktop
Source5:        resolve-update-from-downloads.desktop
Source6:        resolve-aac-settings.desktop
Source7:        resolve-aac-tools-icon-512.png

BuildArch:      noarch

# Only used for validation in %%check and by Copr/mock; plain rpmbuild tolerates
# their absence because the checks are guarded.
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib

Requires:       python3
# ffmpeg (with the aac decoder) comes from RPM Fusion on Fedora, not the base repo.
Requires:       ffmpeg
Requires:       python3-gobject
Requires:       kdialog
Requires:       python3-pyside6
Recommends:     rsms-inter-fonts

%description
DaVinci Resolve on Linux cannot import AAC audio directly. Resolve AAC Tools
watches your media, remuxes AAC into a Resolve-friendly container, and adds a
system tray to control the watchers, launch Resolve, and fix AAC audio in
rendered exports.

This package installs the tools system-wide. Per-user preferences are managed
from the tray and the Resolve AAC Settings window. Resolve menu scripts are
optional and can be installed from Settings.

%prep
%autosetup -n %{srcname}-%{version}

%install
# --- runtime scripts -> /usr/share/resolve-aac-tools ---
install -d %{buildroot}%{sharedir}
install -p -m0755 *.py *.sh %{buildroot}%{sharedir}/

# --- CLI wrappers -> /usr/bin (mirror install_user_tools.sh, pointed at %{sharedir}) ---
install -d %{buildroot}%{_bindir}

cat > %{buildroot}%{_bindir}/resolve-aac-import <<EOF
#!/usr/bin/env bash
exec python3 "%{sharedir}/resolve_aac_import.py" --overwrite --import "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-aac-watch <<EOF
#!/usr/bin/env bash
exec python3 "%{sharedir}/resolve_aac_watch.py" "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-aac-current-clip <<EOF
#!/usr/bin/env bash
exec python3 "%{sharedir}/resolve_aac_timeline.py" --overwrite "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-aac-timeline-watch <<EOF
#!/usr/bin/env bash
exec python3 "%{sharedir}/resolve_aac_timeline_watch.py" "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-aac-timeline-watch-stop <<EOF
#!/usr/bin/env bash
exec python3 "%{sharedir}/resolve_aac_timeline_watch_stop.py" "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-aac-mediapool-watch <<EOF
#!/usr/bin/env bash
exec python3 "%{sharedir}/resolve_aac_mediapool_watch.py" "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-aac-mediapool-watch-stop <<EOF
#!/usr/bin/env bash
exec python3 "%{sharedir}/resolve_aac_mediapool_watch_stop.py" "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-aac-export-watch <<EOF
#!/usr/bin/env bash
exec python3 "%{sharedir}/resolve_aac_export_watch.py" "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-with-aac-mediapool-watch <<EOF
#!/usr/bin/env bash
exec bash "%{sharedir}/resolve-with-aac-mediapool-watch.sh" "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-with-fonts <<EOF
#!/usr/bin/env bash
exec bash "%{sharedir}/resolve-with-fonts.sh" "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-update-from-downloads <<EOF
#!/usr/bin/env bash
exec bash "%{sharedir}/resolve_update_from_downloads.sh" "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-aac-tray <<EOF
#!/usr/bin/env bash
set -euo pipefail

LOG="\${RESOLVE_AAC_TRAY_LOG:-/tmp/resolve_aac_tray.log}"

if pgrep -u "\$(id -u)" -f 'python.*resolve_aac_tray.py' >/dev/null 2>&1; then
  exit 0
fi

setsid "%{sharedir}/resolve_aac_tray.py" "\$@" >>"\$LOG" 2>&1 </dev/null &
disown || true
EOF

cat > %{buildroot}%{_bindir}/resolve-aac-settings <<EOF
#!/usr/bin/env bash
exec python3 "%{sharedir}/resolve_aac_setup.py" "\$@"
EOF

cat > %{buildroot}%{_bindir}/resolve-aac-start <<EOF
#!/usr/bin/env bash
set -euo pipefail

if pgrep -u "\$(id -u)" -f 'python.*resolve_aac_tray.py' >/dev/null 2>&1; then
  mkdir -p "\$HOME/.config/resolve-aac-tools"
  : > "\$HOME/.config/resolve-aac-tools/start_resolve.request"
  exit 0
fi

LOG="\${RESOLVE_AAC_TRAY_LOG:-/tmp/resolve_aac_tray.log}"
setsid "%{sharedir}/resolve_aac_tray.py" --start-resolve "\$@" >>"\$LOG" 2>&1 </dev/null &
disown || true
EOF

chmod 0755 %{buildroot}%{_bindir}/resolve-aac-* %{buildroot}%{_bindir}/resolve-with-* %{buildroot}%{_bindir}/resolve-update-from-downloads

# --- desktop entries -> /usr/share/applications ---
install -d %{buildroot}%{_datadir}/applications
install -p -m0644 %{SOURCE2} %{buildroot}%{_datadir}/applications/%{appid}.desktop
install -p -m0644 %{SOURCE3} %{buildroot}%{_datadir}/applications/resolve-aac-import.desktop
install -p -m0644 %{SOURCE4} %{buildroot}%{_datadir}/applications/resolve-aac-start.desktop
install -p -m0644 %{SOURCE5} %{buildroot}%{_datadir}/applications/resolve-update-from-downloads.desktop
install -p -m0644 %{SOURCE6} %{buildroot}%{_datadir}/applications/resolve-aac-settings.desktop

# --- Discover/GNOME Software metadata -> /usr/share/metainfo ---
install -d %{buildroot}%{_metainfodir}
install -p -m0644 %{SOURCE1} %{buildroot}%{_metainfodir}/%{appid}.metainfo.xml

# --- app icon -> hicolor icon theme (Discover tile, menus, tray) ---
install -d %{buildroot}%{_datadir}/icons/hicolor/512x512/apps
install -p -m0644 %{SOURCE7} %{buildroot}%{_datadir}/icons/hicolor/512x512/apps/%{appid}.png

%check
# Guarded so a bare local rpmbuild without these tools still succeeds.
command -v desktop-file-validate >/dev/null 2>&1 && \
  desktop-file-validate %{buildroot}%{_datadir}/applications/*.desktop || :
command -v appstreamcli >/dev/null 2>&1 && \
  appstreamcli validate --no-net %{buildroot}%{_metainfodir}/%{appid}.metainfo.xml || :

%post
touch --no-create %{_datadir}/icons/hicolor &>/dev/null || :

%postun
if [ $1 -eq 0 ] ; then
    touch --no-create %{_datadir}/icons/hicolor &>/dev/null
    gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :
fi

%posttrans
gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :

%files
%license LICENSE
%doc README.md
%{sharedir}/
%{_bindir}/resolve-aac-import
%{_bindir}/resolve-aac-watch
%{_bindir}/resolve-aac-current-clip
%{_bindir}/resolve-aac-timeline-watch
%{_bindir}/resolve-aac-timeline-watch-stop
%{_bindir}/resolve-aac-mediapool-watch
%{_bindir}/resolve-aac-mediapool-watch-stop
%{_bindir}/resolve-aac-export-watch
%{_bindir}/resolve-with-aac-mediapool-watch
%{_bindir}/resolve-with-fonts
%{_bindir}/resolve-update-from-downloads
%{_bindir}/resolve-aac-tray
%{_bindir}/resolve-aac-settings
%{_bindir}/resolve-aac-start
%{_datadir}/applications/%{appid}.desktop
%{_datadir}/applications/resolve-aac-import.desktop
%{_datadir}/applications/resolve-aac-start.desktop
%{_datadir}/applications/resolve-update-from-downloads.desktop
%{_datadir}/applications/resolve-aac-settings.desktop
%{_metainfodir}/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/512x512/apps/%{appid}.png

%changelog
* Wed Jul 08 2026 RayDurlok <noreply@example.com> - 0.1.14-1
- Re-detect the Resolve version after running the updater (on window focus)

* Wed Jul 08 2026 RayDurlok <noreply@example.com> - 0.1.13-1
- Show only the main "Resolve AAC Tools" menu entry; hide secondary launchers

* Wed Jul 08 2026 RayDurlok <noreply@example.com> - 0.1.12-1
- Ship the app icon (Discover tile, menus, tray)
- Modern setup/settings window; fix ProRes/.mov export remux

* Tue Jul 07 2026 RayDurlok <noreply@example.com> - 0.1.11-1
- Initial RPM packaging: system-wide install, CLI wrappers, tray, Discover metadata
