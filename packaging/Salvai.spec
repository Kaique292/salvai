import zipfile
from pathlib import Path

import imageio_ffmpeg
from PyInstaller.building import splash, splash_templates
from PyInstaller.utils.hooks import collect_all, copy_metadata
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)
ROOT = Path(SPECPATH).resolve().parent
VERSION = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
_v = tuple(int(x) for x in (VERSION.split(".") + ["0"] * 4)[:4])
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_v, prodvers=_v),
    kids=[
        StringFileInfo([StringTable("041604B0", [
            StringStruct("ProductName", "Salvaí"),
            StringStruct("FileDescription", "Salvaí"),
            StringStruct("FileVersion", VERSION),
            StringStruct("ProductVersion", VERSION),
            StringStruct("OriginalFilename", "Salvai.exe"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
    ],
)

ff_src = sorted((Path(imageio_ffmpeg.__file__).parent / "binaries").glob("ffmpeg*.exe"))[0]
ff_zip = ROOT / "build" / "cache" / "ffmpeg.zip"
if not ff_zip.exists() or zipfile.ZipFile(ff_zip).namelist() != [ff_src.name]:
    ff_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ff_zip, "w", zipfile.ZIP_LZMA) as z:
        z.write(ff_src, ff_src.name)

datas = [(str(ROOT / "src" / "ui"), "ui"), (str(ff_zip), "."), (str(ROOT / "version.txt"), ".")]
datas += copy_metadata("yt-dlp")
datas.append((str(ROOT / "assets" / "icon.ico"), "."))
binaries, hiddenimports = [], []
d, b, h = collect_all("yt_dlp_ejs")
datas += d
binaries += b
hiddenimports += h

a = Analysis(
    [str(ROOT / "src" / "app.py")],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports + ["pystray._win32"],
    excludes=[
        "cryptography",
        "secretstorage",
        "tkinter",
        "PIL._avif",
        "PIL.AvifImagePlugin",
        "PIL._webp",
        "PIL.WebPImagePlugin",
        "PIL.ImageTk",
        "PIL._imagingtk",
    ],
)
a.datas = [e for e in a.datas if not e[0].startswith("imageio_ffmpeg\\binaries")]
a.binaries = [e for e in a.binaries if not e[0].startswith("imageio_ffmpeg\\binaries")]


SPLASH_TCL = r"""
image create photo splash_image
splash_image put $_image_data
unset _image_data
package require Tk

set W [image width splash_image]
set H [image height splash_image]
if {[info exists _pyi_screen_geometry]} {
    set dx $_pyi_screen_geometry(x); set dy $_pyi_screen_geometry(y)
    set dw $_pyi_screen_geometry(width); set dh $_pyi_screen_geometry(height)
} else {
    set dx 0; set dy 0; set dw [winfo screenwidth .]; set dh [winfo screenheight .]
}
set x_position [expr {int($dx + 0.5*($dw - $W))}]
set y_position [expr {int($dy + 0.5*($dh - $H))}]

canvas .c -width $W -height $H -borderwidth 0 -highlightthickness 0 -background magenta
.c create image [expr {$W/2}] [expr {$H/2}] -image splash_image
font create stFont -family "Segoe UI" -size 9
font create pctFont -family "Segoe UI Semibold" -size 9

set BX 38; set BY 196; set BW [expr {$W - 76}]
.c create text $BX [expr {$BY - 12}] -anchor sw -fill #8B8B96 -font stFont -text "Descompactando arquivos…" -tag label
.c create text [expr {$BX + $BW}] [expr {$BY - 12}] -anchor se -fill #EDEDF0 -font pctFont -text "0%" -tag pct
.c create line $BX $BY [expr {$BX + $BW}] $BY -width 6 -capstyle round -fill #26262E
.c create line $BX $BY [expr {$BX + 1}] $BY -width 6 -capstyle round -fill #E5484D -tag bar
.c create line 0 $BY 1 $BY -width 6 -capstyle round -fill #F2898C -tag shine -state hidden
.c create text [expr {$W/2}] [expr {$H - 18}] -anchor s -fill #4A4A55 -font stFont -text "Isso leva só alguns segundos" -tag foot

set status_text ""
set target 0.0
set shown 0.0
set nfiles 0
set phase 0.0

set started [clock milliseconds]
set python_up 0

proc on_status {args} {
    global status_text target python_up
    if {[string index $status_text 0] eq "@"} {
        set python_up 1
        set parts [split [string range $status_text 1 end] "|"]
        set t [expr {[lindex $parts 0] / 100.0}]
        if {$t > $target} { set target $t }
        .c itemconfigure label -text [lindex $parts 1]
    }
}
trace add variable status_text write on_status

proc tick {} {
    global target shown phase BX BY BW started python_up
    if {!$python_up} {
        set secs [expr {([clock milliseconds] - $started) / 1000.0}]
        set target [expr {max($target, 0.6 * (1 - exp(-$secs / 1.1)))}]
    }
    set shown [expr {$shown + ($target - $shown) * 0.10}]
    set target [expr {min(0.97, $target + 0.0004)}]
    set x [expr {$BX + max(1.0, $BW * $shown)}]
    .c coords bar $BX $BY $x $BY
    .c itemconfigure pct -text "[expr {int($shown * 100 + 0.5)}]%"
    set fill [expr {$x - $BX}]
    if {$fill > 40} {
        set phase [expr {fmod($phase + 3.5, $fill + 80)}]
        set s [expr {max($BX, $BX + $phase - 60)}]
        set e [expr {min($x, $BX + $phase)}]
        if {$e > $s + 2} {
            .c coords shine $s $BY $e $BY
            .c itemconfigure shine -state normal
        } else {
            .c itemconfigure shine -state hidden
        }
    }
    after 16 tick
}
tick

pack .c
wm attributes . -transparentcolor magenta
wm overrideredirect . 1
wm geometry . +${x_position}+${y_position}
wm attributes . -topmost 0
raise .
"""


def build_script(text_options=None, always_on_top=False):
    return splash_templates.ipc_script + SPLASH_TCL


splash.splash_templates.build_script = build_script

pyz = PYZ(a.pure)
spl = Splash(
    str(ROOT / "assets" / "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    minify_script=False,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    spl,
    spl.binaries,
    [],
    name="Salvai",
    icon=str(ROOT / "assets" / "icon.ico"),
    version=version_info,
    console=False,
    upx=False,
)
