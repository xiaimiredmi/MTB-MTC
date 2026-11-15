import ctypes
import ctypes.wintypes as wt

shlwapi = ctypes.WinDLL("shlwapi")
ASSOCSTR_EXECUTABLE = 2
ASSOCSTR_COMMAND = 1
ASSOCSTR_FRIENDLYAPPNAME = 4

def query(str_type, assoc):
    buf = ctypes.create_unicode_buffer(1024)
    size = wt.DWORD(len(buf))
    rc = shlwapi.AssocQueryStringW(0, str_type, assoc, None, buf, ctypes.byref(size))
    if rc != 0:
        return "ERR 0x%08X" % rc
    return buf.value

for ext in (".mtb", ".mtc"):
    print(ext, "exe    :", query(ASSOCSTR_EXECUTABLE, ext))
    print(ext, "command:", query(ASSOCSTR_COMMAND, ext))
    print(ext, "appname:", query(ASSOCSTR_FRIENDLYAPPNAME, ext))
