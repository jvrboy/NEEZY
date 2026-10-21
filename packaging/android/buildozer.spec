[app]
title = NEEZY
package.name = neezy
package.domain = app.neezy
source.dir = .
source.include_exts = py,json,pem
source.exclude_dirs = bin,build,__pycache__
version = 1.6.0
requirements = python3,kivy==2.3.1
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
