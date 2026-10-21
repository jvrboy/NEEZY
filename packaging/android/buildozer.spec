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

# Pin python-for-android: master moved to Python 3.14 and its libffi recipe
# fails to autoreconf on the CI runner. v2024.01.21 builds kivy 2.3.1 with NDK 25b.
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 0
