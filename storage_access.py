"""Android 11+ keeps most folders private unless the person allows 'All files access'.

On a computer these functions do nothing and say everything is allowed.
"""
from kivy.utils import platform


def has_all_files_access():
    if platform != "android":
        return True
    try:
        from jnius import autoclass

        return bool(autoclass("android.os.Environment").isExternalStorageManager())
    except Exception:
        return True  # very old Android: the normal storage permission is enough


def ask_all_files_access():
    """Open the Android settings page where the person can switch it on."""
    if platform != "android":
        return
    try:
        from jnius import autoclass

        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        Uri = autoclass("android.net.Uri")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
        intent.setData(Uri.parse("package:" + activity.getPackageName()))
        activity.startActivity(intent)
    except Exception:
        pass


def phone_storage_root():
    """The top of the phone's shared storage ('/storage/emulated/0'), or None."""
    if platform != "android":
        return None
    try:
        from android.storage import primary_external_storage_path

        return primary_external_storage_path()
    except Exception:
        return "/storage/emulated/0"
