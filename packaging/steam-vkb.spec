# Experimental RPM recipe for image-side layering.
#
# This vendors the pywayland dependency at BUILD time: it needs network from
# PyPI (or STEAM_VKB_VENDOR_WHEELS pointing at a directory carrying the
# pywayland 0.4.19 wheel for the build CPython).  It also bakes a compiled
# venv, so it is arch-specific and is tied to the build interpreter.
# install.sh is the proven path today; this spec is for future image builds.
#
# Build:  rpmbuild -bb packaging/steam-vkb.spec
# Layer:  rpm-ostree install <result.rpm>
Name:           steam-vkb
Version:        0.1.0
Release:        1%{?dist}
Summary:        Steam Game Mode on-screen keyboard as a Plasma virtual keyboard option
License:        MIT
URL:            https://github.com/oemasync/steam-vKB

%global svk_root %{_libexecdir}/steam-vkb
%global svk_venv %{svk_root}/venv

%description
Bridges KWin's input-method socket to the Steam client: selecting
"Steam Game Mode Keyboard" in System Settings -> Keyboard -> Virtual Keyboard
makes KWin launch this bridge, which opens the deck keyboard overlay for
focused text fields in desktop mode.

%prep
# Sources live in this repository; copy them into the build dir wholesale.
cp -r "$(dirname %{_sourcedir})/src"  src
cp    "$(dirname %{_sourcedir})/data" data

%install
mkdir -p %{buildroot}%{svk_root}/libexec
cp -r src/steam_vkb %{buildroot}%{svk_root}/libexec/
python3 -m venv %{buildroot}%{svk_venv}
if [ -n "$STEAM_VKB_VENDOR_WHEELS" ]; then
    %{buildroot}%{svk_venv}/bin/pip install --no-index \
        --find-links "$STEAM_VKB_VENDOR_WHEELS" "pywayland==0.4.19"
else
    %{buildroot}%{svk_venv}/bin/pip install "pywayland==0.4.19"
fi
install -D -m 755 data/steam-vkb.sh %{buildroot}%{_bindir}/steam-vkb
install -D data/steam-vkb.desktop %{buildroot}%{_datadir}/applications/steam-vkb.desktop
chmod -R a+rX %{buildroot}%{svk_root}

%files
%{svk_root}/
%{_bindir}/steam-vkb
%{_datadir}/applications/steam-vkb.desktop
