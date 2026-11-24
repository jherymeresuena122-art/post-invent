[app]
title = Post Invent v1
package.name = postinventv1
package.domain = org.pod
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #EAB75C
source.dir = .
source.include_exts = py,kv,png,jpg,ttf
source.exclude_patterns = test_database.py,README.md
version = 1.1
requirements = hostpython3==3.11.5,python3==3.11.5,kivy==2.3.0,pillow,sqlite3
orientation = portrait
fullscreen = 0
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES
android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.ndk = 25b
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
