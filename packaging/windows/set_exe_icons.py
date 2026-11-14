"""Replace every icon group of a Windows executable with one .ico file.

    python set_exe_icons.py celtx.exe openscript.ico          (runs on Windows)
    python set_exe_icons.py --check celtx.exe openscript.ico  (any OS, needs pefile)

celtx.exe has three icon groups ("0", 1 and 32512); rcedit only replaces one,
and Windows/Wine pick different groups for the taskbar, Alt+Tab or the macOS
Dock. This writes the OpenScript images once and points every group at them,
keeping each group's language so the old entries are replaced, not doubled.
"""
import ctypes
import hashlib
import struct
import sys

RT_ICON, RT_GROUP_ICON = 3, 14
FIRST_NEW_ICON_ID = 500


def read_ico(path):
    with open(path, "rb") as f:
        data = f.read()
    _reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert kind == 1, "not an .ico file"
    images = []
    for i in range(count):
        w, h, colors, res, planes, bpp, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        images.append(((w, h, colors, res, planes, bpp), data[offset:offset + size]))
    return images


def icon_groups(exe):
    """{group name or id: language} using pefile."""
    import pefile
    pe = pefile.PE(exe, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    groups = {}
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if kind.id == RT_GROUP_ICON:
            for entry in kind.directory.entries:
                name = str(entry.name) if entry.name else entry.id
                groups[name] = entry.directory.entries[0].id   # language
    pe.close()
    return groups


def replace(exe, ico):
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.BeginUpdateResourceW.restype = wintypes.HANDLE
    k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k32.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                    wintypes.WORD, ctypes.c_void_p, wintypes.DWORD]
    k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]

    def res_name(name):
        if isinstance(name, int):
            return ctypes.c_void_p(name)                       # MAKEINTRESOURCE
        return ctypes.cast(ctypes.c_wchar_p(name), ctypes.c_void_p)

    images = read_ico(ico)
    groups = icon_groups(exe)
    languages = set(groups.values())
    handle = k32.BeginUpdateResourceW(exe, False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    directory = struct.pack("<HHH", 0, 1, len(images))
    for i, ((w, h, colors, res, planes, bpp), blob) in enumerate(images):
        icon_id = FIRST_NEW_ICON_ID + i
        buf = ctypes.create_string_buffer(blob, len(blob))
        for lang in languages:
            if not k32.UpdateResourceW(handle, res_name(RT_ICON), res_name(icon_id), lang, buf, len(blob)):
                raise ctypes.WinError(ctypes.get_last_error())
        directory += struct.pack("<BBBBHHIH", w, h, colors, res, planes, bpp, len(blob), icon_id)
    buf = ctypes.create_string_buffer(directory, len(directory))
    for name, lang in groups.items():
        if not k32.UpdateResourceW(handle, res_name(RT_GROUP_ICON), res_name(name), lang, buf, len(directory)):
            raise ctypes.WinError(ctypes.get_last_error())
    if not k32.EndUpdateResourceW(handle, False):
        raise ctypes.WinError(ctypes.get_last_error())
    print("icon groups replaced:", ", ".join(str(g) for g in groups))


def check(exe, ico):
    """Every icon group must reference exactly the images of the .ico file."""
    import pefile
    wanted = sorted(hashlib.sha256(blob).hexdigest() for _hdr, blob in read_ico(ico))
    pe = pefile.PE(exe)
    icons = {}
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if kind.id == RT_ICON:
            for e in kind.directory.entries:
                d = e.directory.entries[0].data.struct
                icons[e.id] = hashlib.sha256(pe.get_data(d.OffsetToData, d.Size)).hexdigest()
    ok = True
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if kind.id == RT_GROUP_ICON:
            for e in kind.directory.entries:
                d = e.directory.entries[0].data.struct
                raw = pe.get_data(d.OffsetToData, d.Size)
                count = struct.unpack_from("<H", raw, 4)[0]
                ids = [struct.unpack_from("<H", raw, 6 + 14 * i + 12)[0] for i in range(count)]
                got = sorted(icons.get(i, "?") for i in ids)
                name = str(e.name) if e.name else e.id
                print("group %s: %s" % (name, "OpenScript" if got == wanted else "NOT replaced"))
                ok = ok and got == wanted
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1] == "--check":
        sys.exit(check(sys.argv[2], sys.argv[3]))
    replace(sys.argv[1], sys.argv[2])
    sys.exit(check(sys.argv[1], sys.argv[2]))
