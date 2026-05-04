import time
import gc
import os
from media.sensor import *
import image

SAVE_BASE = "/data/snapshot/picture_get/"

def ensure_dir(directory):
    if not directory or directory == "/":
        return
    directory = directory.rstrip("/")
    try:
        os.stat(directory)
        return
    except OSError:
        if "/" in directory:
            parent = directory[:directory.rindex("/")]
            if parent and parent != directory:
                ensure_dir(parent)
        try:
            os.mkdir(directory)
        except OSError:
            try:
                os.stat(directory)
            except:
                pass

def save_photo(img, run_dir, seq_num):
    fname = "PIC%06d.jpg" % seq_num
    bases = ["/data/snapshot/", "/sdcard/snapshot/"]
    for base in bases:
        try:
            ensure_dir(base + run_dir + "/")
            path = base + run_dir + "/" + fname
            if not img:
                continue
            try:
                img.save(path)
            except Exception:
                try:
                    if hasattr(img, "compress"):
                        buf = img.compress(quality=85)
                        with open(path, "wb") as f:
                            f.write(buf)
                    else:
                        raise
                except Exception:
                    try:
                        bmp_path = base + run_dir + ("/PIC%06d.bmp" % seq_num)
                        img.save(bmp_path)
                        path = bmp_path
                    except Exception:
                        continue
            try:
                os.stat(path)
                return path, fname
            except OSError:
                continue
        except Exception:
            continue
    return None, fname

def _load_boot_seq():
    try:
        with open(SAVE_BASE + "boot_seq.txt", "r") as f:
            n = int(f.read().strip())
            if n >= 1:
                return n
    except Exception:
        pass
    return 1

def _save_boot_seq(n):
    try:
        with open(SAVE_BASE + "boot_seq.txt", "w") as f:
            f.write(str(int(n)))
    except Exception:
        pass

def _load_seq(dd):
    try:
        with open(SAVE_BASE + dd + "/seq.txt", "r") as f:
            n = int(f.read().strip())
            if n >= 1:
                return n
    except Exception:
        pass
    return 1

def _save_seq(dd, n):
    try:
        with open(SAVE_BASE + dd + "/seq.txt", "w") as f:
            f.write(str(int(n)))
    except Exception:
        pass
