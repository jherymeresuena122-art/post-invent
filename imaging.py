"""Profile pictures: crop to a square, shrink, save inside the app's own folder."""
import os

from PIL import Image, ImageOps

AVATAR_SIZE = 256


def make_avatar(source_path, folder, name, size=AVATAR_SIZE):
    """Read any picture, save a small square copy into folder, return its path.

    The copy is the app's own, so the profile picture keeps working even if the
    original is moved or deleted. A new file name is used every time so the app
    never shows an old cached picture.
    """
    with Image.open(source_path) as img:
        img = ImageOps.exif_transpose(img)          # phone photos are often rotated
        img = ImageOps.fit(img.convert("RGB"), (size, size), Image.LANCZOS)
        os.makedirs(folder, exist_ok=True)
        stamp = 0
        while True:
            path = os.path.join(folder, f"{name}_{stamp}.jpg")
            if not os.path.exists(path):
                break
            stamp += 1
        img.save(path, "JPEG", quality=88)
    return path


def remove_file(path):
    """Delete an old profile picture. Never raises."""
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
