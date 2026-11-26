"""Phone camera, gallery and the system "save / open file" screens (Android).

Everything goes through Android's own screens, so the app does not need any
storage permission for these and nothing can freeze on a huge folder.

Each function takes a `callback` that is called later, on the app's normal
thread, with the result (a file path, or None if the person cancelled).
On a PC (no Android) these functions call callback(None) and return False,
so the caller can fall back to the in-app file browser.
"""
import os
import shutil
import time

from kivy.clock import Clock
from kivy.utils import platform

IS_ANDROID = platform == "android"

_GALLERY, _CAMERA, _SAVE, _OPEN = 7101, 7102, 7103, 7104
_RESULT_OK = -1
_pending = {}          # request code -> handler
last_error = ""        # why the last call failed (shown to the person instead of crashing)


def _reset():
    global last_error
    last_error = ""


def _fail(err, callback, value=None):
    global last_error
    last_error = f"{type(err).__name__}: {err}"[:300]
    callback(value)
    return False


def _activity():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity


def _on_result(request_code, result_code, intent):
    handler = _pending.pop(request_code, None)
    if handler is not None:
        # Android calls this from its own thread; screens must be touched on Kivy's.
        Clock.schedule_once(lambda dt: handler(result_code, intent), 0)


def _start(intent, request_code, handler):
    from android import activity
    if not _pending:
        activity.bind(on_activity_result=_on_result)
    _pending[request_code] = handler
    _activity().startActivityForResult(intent, request_code)


def _copy_from_uri(uri, target):
    """Copy what a content:// address points to into a real file."""
    resolver = _activity().getContentResolver()
    pfd = resolver.openFileDescriptor(uri, "r")
    fd = pfd.detachFd()
    with os.fdopen(fd, "rb") as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return target


def _copy_to_uri(source, uri):
    resolver = _activity().getContentResolver()
    pfd = resolver.openFileDescriptor(uri, "wt")
    fd = pfd.detachFd()
    with open(source, "rb") as src, os.fdopen(fd, "wb") as dst:
        shutil.copyfileobj(src, dst)


def _temp_path(cache_dir, suffix):
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"incoming_{int(time.time() * 1000)}{suffix}")


# ------------------------------------------------------------------ pictures
def pick_from_gallery(callback, cache_dir):
    """Open the phone's gallery / photo picker. callback(path_or_None)."""
    if not IS_ANDROID:
        callback(None)
        return False
    _reset()
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")

        def done(result_code, intent):
            if result_code != _RESULT_OK or intent is None or intent.getData() is None:
                return callback(None)
            try:
                callback(_copy_from_uri(intent.getData(), _temp_path(cache_dir, ".jpg")))
            except Exception as err:
                _fail(err, callback)

        # ACTION_GET_CONTENT already shows Android's own chooser, so no createChooser
        intent = Intent(Intent.ACTION_GET_CONTENT)
        intent.setType("image/*")
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        _start(intent, _GALLERY, done)
        return True
    except Exception as err:
        return _fail(err, callback)


def take_photo(callback, cache_dir):
    """Open the phone's camera. callback(path_or_None)."""
    if not IS_ANDROID:
        callback(None)
        return False
    _reset()
    try:
        from jnius import autoclass, cast
        Intent = autoclass("android.content.Intent")
        MediaStore = autoclass("android.provider.MediaStore")
        Images = autoclass("android.provider.MediaStore$Images$Media")
        ContentValues = autoclass("android.content.ContentValues")

        resolver = _activity().getContentResolver()
        values = ContentValues()
        values.put("_display_name", f"pod_profile_{int(time.time())}.jpg")
        values.put("mime_type", "image/jpeg")
        values.put("relative_path", "Pictures/ThePod")   # ignored by phones older than Android 10
        uri = resolver.insert(Images.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            raise RuntimeError("the phone would not make a place for the photo")

        def done(result_code, intent):
            path = None
            error = None
            try:
                if result_code == _RESULT_OK:
                    path = _copy_from_uri(uri, _temp_path(cache_dir, ".jpg"))
            except Exception as err:
                error = err
            try:
                resolver.delete(uri, None, None)    # do not leave a second copy in the gallery
            except Exception:
                pass
            if error is not None:
                _fail(error, callback)
            else:
                callback(path)

        intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
        # the Uri must be passed as a Parcelable, or Android sees it as a String
        intent.putExtra(MediaStore.EXTRA_OUTPUT, cast("android.os.Parcelable", uri))
        intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION)
        _start(intent, _CAMERA, done)
        return True
    except Exception as err:
        return _fail(err, callback)


# ------------------------------------------------------------ backup files
def save_file_dialog(source_path, suggested_name, callback):
    """Android's 'Save to...' screen (Drive, Downloads, SD card ...).
    Copies source_path to the place the person picks. callback(True/False)."""
    if not IS_ANDROID:
        callback(False)
        return False
    _reset()
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")

        def done(result_code, intent):
            if result_code != _RESULT_OK or intent is None or intent.getData() is None:
                return callback(False)
            try:
                _copy_to_uri(source_path, intent.getData())
                callback(True)
            except Exception as err:
                _fail(err, callback, False)

        intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("application/octet-stream")
        intent.putExtra(Intent.EXTRA_TITLE, suggested_name)
        _start(intent, _SAVE, done)
        return True
    except Exception as err:
        return _fail(err, callback, False)


def open_file_dialog(callback, cache_dir):
    """Android's 'Open from...' screen. callback(path_or_None) with a private copy."""
    if not IS_ANDROID:
        callback(None)
        return False
    _reset()
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")

        def done(result_code, intent):
            if result_code != _RESULT_OK or intent is None or intent.getData() is None:
                return callback(None)
            try:
                callback(_copy_from_uri(intent.getData(), _temp_path(cache_dir, ".podbackup")))
            except Exception as err:
                _fail(err, callback)

        intent = Intent(Intent.ACTION_GET_CONTENT)
        intent.setType("*/*")
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        _start(intent, _OPEN, done)
        return True
    except Exception as err:
        return _fail(err, callback)


def clean_cache(cache_dir):
    """Delete leftovers of earlier pictures / backups. Never raises."""
    try:
        for name in os.listdir(cache_dir):
            if name.startswith("incoming_"):
                os.remove(os.path.join(cache_dir, name))
    except OSError:
        pass
