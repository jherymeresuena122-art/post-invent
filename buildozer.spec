[app]
title = Post Invent v1
package.name = postinventv1
package.domain = org.pod
source.dir = .
source.include_exts = py,kv,png,jpg,ttf
source.exclude_patterns = test_database.py,README.md
version = 1.0
requirements = python3,kivy==2.3.0,pillow,sqlite3
orientation = portrait
fullscreen = 0
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
