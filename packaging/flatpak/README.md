# IngeCAD as a Flatpak

For the engineer who never opens a terminal: download `IngeCAD.flatpak`,
double-click it, and GNOME Software / KDE Discover installs it — the
Freedesktop runtime comes from Flathub automatically (the bundle carries
`--runtime-repo`). Deliberately NOT on Flathub for now; this is
self-distribution, the same road IngePresupuestos already walks
(`downloads.ingepresupuestos.com/flatpak/`).

    packaging/flatpak/build-flatpak.sh            # build + install (user)
    packaging/flatpak/build-flatpak.sh --bundle   # + .staging/IngeCAD.flatpak

The manifest compiles LibreDWG from the pristine release plus
`tools/libredwg-patches/current/` — the same converters the AppImage
carries — and installs them where `core.paths.app_root()` looks. The app
module lets pip reach the network for wheels, which is exactly what Flathub
forbids: if this ever goes there, that module becomes generated offline
sources (flatpak-pip-generator) and this file is the reminder.

Sandbox: wayland + fallback-x11 + dri + `--filesystem=home`, and **no
network** — IngeCAD needs none, and the sandbox should say so.

Next step (decided, not yet built): the signed OSTree repo on R2 behind
ingecad.org, mirroring IngePresupuestos' `publish-flatpak.yml`, so installs
update themselves. Needs from Marco: a GPG signing key and the R2 bucket +
subdomain. Until then the bundle rides each GitHub release.
