import os
import subprocess
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog
import platform
import socket
from PIL import Image, ImageTk


# ── Utilities ────────────────────────────────────────────────────────────────

def get_software_version():
    try:
        with open("environment.yaml", "r") as f:
            for line in f:
                if line.startswith("name: timon_"):
                    return line.split("name: timon_")[1].strip()
    except Exception:
        pass
    return "unknown"

def find_available_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port

host_port = find_available_port()

def check_container_preparation():
    try:
        r = subprocess.run(["docker", "image", "ls", "-q", "timon:dev"],
                           capture_output=True, text=True, timeout=5)
        return bool(r.stdout.strip())
    except Exception:
        return False

def check_docker_available():
    try:
        r = subprocess.run(["docker", "info"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        return r.returncode == 0
    except Exception:
        return False

def center_window(win, w, h):
    win.update_idletasks()
    x = (win.winfo_screenwidth()  // 2) - (w // 2)
    y = (win.winfo_screenheight() // 2) - (h // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


# ── Docker ───────────────────────────────────────────────────────────────────

def run_docker_logic(input_path, kraken_db, gtdbtk_db):
    input_path = os.path.abspath(input_path)
    cmd = [
        "docker", "run", "-d", "--rm",
        "-p", f"{host_port}:8000",
        "-v", f"{input_path}:/app/data",
        "-e", "INPUT_DIR=/app/data",
    ]
    
    if kraken_db:
        cmd += ["-v", f"{os.path.abspath(kraken_db)}:/app/kraken_db:ro",
                "-e", "KRAKEN_DB=/app/kraken_db"]
    if gtdbtk_db:
        cmd += ["-v", f"{os.path.abspath(gtdbtk_db)}:/app/gtdbtk_db:ro",
                "-e", "GTDBTK_DB=/app/gtdbtk_db"]
    cmd.append("timon:dev")
    subprocess.run(cmd)
    time.sleep(5)
    webbrowser.open(f"http://localhost:{host_port}")


# ── Custom widgets ───────────────────────────────────────────────────────────

C = {
    "bg":        "#ffffff",
    "surface":   "#f9fafb",
    "surface2":  "#f3f4f6",
    "border":    "#e5e7eb",
    "border2":   "#d1d5db",
    "text":      "#111827",
    "text_dim":  "#6b7280",
    "text_mid":  "#4b5563",
    "accent":    "#2563eb",
    "accent_dim": "#1d4ed8",
    "green":     "#16a34a",
    "green_dim": "#15803d",
    "amber":     "#d97706",
    "red":       "#dc2626",
    "panel":     "#ffffff",
}

MONO = "Courier"  # IBM Plex Mono fallback; replace with "IBM Plex Mono" if installed


class FlatButton(tk.Canvas):
    """
    A Canvas-based flat button that supports proper hover states,
    since tk.Button styling is platform-uncontrollable.
    """
    def __init__(self, parent, text, command=None,
                 fg=C["text"], bg=C["surface2"], fg_hover=C["text"],
                 bg_hover=C["border2"], border_color=C["border2"],
                 width=200, height=36, font_size=11, **kw):
        super().__init__(parent, width=width, height=height,
                         bg=parent["bg"], highlightthickness=0, cursor="pointinghand", **kw)
        self._text       = text
        self._command    = command
        self._fg         = fg
        self._bg         = bg
        self._fg_hover   = fg_hover
        self._bg_hover   = bg_hover
        self._border     = border_color
        self._width      = width
        self._height     = height
        self._font       = (MONO, font_size)
        self._hovered    = False
        self._draw()
        self.bind("<Enter>",         self._on_enter)
        self.bind("<Leave>",         self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)

    def _draw(self):
        self.delete("all")
        bg  = self._bg_hover   if self._hovered else self._bg
        fg  = self._fg_hover   if self._hovered else self._fg
        bdr = C["accent"]      if self._hovered else self._border
        # Border rect
        self.create_rectangle(0, 0, self._width - 1, self._height - 1,
                               fill=bg, outline=bdr, width=1)
        self.create_text(self._width // 2, self._height // 2,
                         text=self._text, fill=fg,
                         font=self._font, anchor="center")

    def _on_enter(self, _):
        self._hovered = True;  self._draw()

    def _on_leave(self, _):
        self._hovered = False; self._draw()

    def _on_press(self, _):
        if self._command:
            self._command()

    def set_text(self, t):
        self._text = t; self._draw()

    def disable(self):
        self.unbind("<Enter>"); self.unbind("<Leave>"); self.unbind("<ButtonPress-1>")
        self._bg = C["border"]; self._fg = C["text_dim"]
        self._hovered = False;  self._draw()


class StatusDot(tk.Canvas):
    """Small indicator dot: grey (unset) → blue (set) → green (ready)."""
    D = 8
    def __init__(self, parent, **kw):
        super().__init__(parent, width=self.D, height=self.D,
                         bg=parent["bg"], highlightthickness=0, **kw)
        self._state = "unset"
        self._draw()

    def _draw(self):
        color = {"unset": C["border2"], "set": C["accent"], "ready": C["green"]}[self._state]
        self.delete("all")
        self.create_oval(0, 0, self.D, self.D, fill=color, outline="")

    def set_state(self, state):   # "unset" | "set" | "ready"
        self._state = state; self._draw()


# ── Launcher window ──────────────────────────────────────────────────────────

class LauncherWindow(tk.Toplevel):

    W, H = 620, 340

    def __init__(self, master):
        super().__init__(master)
        self.withdraw()
        self.master      = master
        self._kraken_db  = ""
        self._gtdbtk_db  = ""
        self._input_path = ""

        self.configure(bg=C["bg"])
        self.title("timon")
        self.resizable(False, False)
        center_window(self, self.W, self.H)
        self.protocol("WM_DELETE_WINDOW", lambda: master.destroy())

        self._build()
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))

    # ── layout ──────────────────────────────────────────────────

    def _build(self):
        # ── Left panel (branding) ────────────────────────────────
        left = tk.Frame(self, bg=C["panel"], width=180)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        try:
            img = Image.open("timon/app/static/img/timon_logo_light.png")
            img.thumbnail((140, 100), Image.LANCZOS)
            self._logo = ImageTk.PhotoImage(img)
            tk.Label(left, image=self._logo, bg=C["panel"],
                     bd=0, highlightthickness=0).pack(pady=(36, 0))
        except Exception:
            tk.Label(left, text="timon", font=(MONO, 22, "bold"),
                     bg=C["panel"], fg=C["text"]).pack(pady=(48, 0))

        tk.Label(left, text=f"{get_software_version()}",
                 font=(MONO, 9), bg=C["panel"],
                 fg=C["text_dim"]).pack(pady=(6, 0))

        # Status pills at bottom of left panel
        pill_frame = tk.Frame(left, bg=C["panel"])
        pill_frame.pack(side="bottom", pady=20)
        self._docker_ok    = check_docker_available()
        self._container_ok = check_container_preparation()
        self._pill("docker",   "ON"    if self._docker_ok    else "OFF",
                   C["green"] if self._docker_ok    else C["red"], pill_frame)
        self._pill("image",    "ready" if self._container_ok else "missing",
                   C["green"] if self._container_ok else C["amber"], pill_frame)

        # ── Vertical divider ─────────────────────────────────────
        tk.Frame(self, bg=C["border"], width=1).pack(side="left", fill="y")

        # ── Right panel (controls) ───────────────────────────────
        right = tk.Frame(self, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)

        # Header
        hdr = tk.Frame(right, bg=C["bg"])
        hdr.pack(fill="x", padx=28, pady=(28, 0))
        tk.Label(hdr, text="select local taxonomy databases",
                 font=(MONO, 9), bg=C["bg"], fg=C["text_dim"],
                 anchor="w").pack(fill="x", pady=(2, 0))

        # Divider
        tk.Frame(right, bg=C["border"], height=1).pack(fill="x", padx=28, pady=(14, 0))

        # DB rows
        self._dots = {}
        self._path_labels = {}
        self._kraken_row  = self._db_row(right, "kraken2",  "Kraken2 database",  self._pick_kraken)
        self._gtdbtk_row  = self._db_row(right, "gtdbtk",   "GTDB-Tk database",  self._pick_gtdbtk)

        # Divider
        tk.Frame(right, bg=C["border"], height=1).pack(fill="x", padx=28, pady=(18, 0))

        # Start button — full width accent
        btn_frame = tk.Frame(right, bg=C["bg"])
        btn_frame.pack(fill="x", padx=28, pady=(14, 0))
        self._start_btn = FlatButton(
            btn_frame,
            text="▶ select input data & start",
            command=self._launch,
            fg=C["accent"], fg_hover="#ffffff",
            bg=C["bg"], bg_hover=C["accent"],
            border_color=C["accent"],
            width=self.W - 180 - 56 - 2,
            height=40,
            font_size=12,
        )
        self._start_btn.pack()

    def _pill(self, label, value, color, parent):
        row = tk.Frame(parent, bg=C["panel"])
        row.pack(fill="x", padx=16, pady=2)
        tk.Label(row, text=label, font=(MONO, 9), bg=C["panel"],
                 fg=C["text_dim"], width=7, anchor="w").pack(side="left")
        tk.Label(row, text=value,  font=(MONO, 9, "bold"), bg=C["panel"],
                 fg=color, anchor="w").pack(side="left")

    def _db_row(self, parent, key, label, pick_fn):
        row = tk.Frame(parent, bg=C["bg"])
        row.pack(fill="x", padx=28, pady=(14, 0))

        # Dot + label
        left = tk.Frame(row, bg=C["bg"])
        left.pack(side="left", fill="y")
        dot = StatusDot(left)
        dot.pack(pady=(3, 0))
        self._dots[key] = dot

        info = tk.Frame(row, bg=C["bg"])
        info.pack(side="left", padx=(10, 0), fill="x", expand=True)
        tk.Label(info, text=label, font=(MONO, 10, "bold"),
                 bg=C["bg"], fg=C["text"], anchor="w").pack(fill="x")
        path_lbl = tk.Label(info, text="not selected",
                            font=(MONO, 8), bg=C["bg"],
                            fg=C["text_dim"], anchor="w")
        path_lbl.pack(fill="x")
        self._path_labels[key] = path_lbl

        # Button
        btn = FlatButton(
            row, text="browse",
            command=pick_fn,
            fg=C["text_mid"], fg_hover=C["text"],
            bg=C["surface"], bg_hover=C["surface2"],
            border_color=C["border2"],
            width=74, height=30, font_size=10,
        )
        btn.pack(side="right")
        return row

    def _set_path_kraken(self, key, path):
        short = "…/" + os.path.basename(path) if path else "not selected"
        color = C["text_mid"] if path else C["text_dim"]
        self._path_labels[key].config(text=short, fg=color)
        self._dots[key].set_state("set" if path else "unset")
    
    def _set_path_gtdbtk(self, key, path):
        short = "…/" + os.path.basename(path) if path else "not selected"
        color = C["text_mid"] if path else C["text_dim"]
        self._path_labels[key].config(text=short, fg=color)
        self._dots[key].set_state("set" if path else "unset")

    # ── pickers ─────────────────────────────────────────────────

    def _pick_kraken(self):
        path = filedialog.askdirectory(title="Select Kraken2 database folder")
        if path:
            self._kraken_db = path
            self._set_path_kraken("kraken2", path)

    def _pick_gtdbtk(self):
        path = filedialog.askdirectory(title="Select GTDB-Tk database folder")
        if path:
            self._gtdbtk_db = path
            self._set_path_gtdbtk("gtdbtk", path)

    # ── launch ──────────────────────────────────────────────────

    def _launch(self):
        path = filedialog.askdirectory(title="Select analysis folder (FASTQ files)")
        if not path:
            return
        self._input_path = path
        self._start_btn.set_text("launching…")
        self._start_btn.disable()

        def _run():
            run_docker_logic(self._input_path, self._kraken_db, self._gtdbtk_db)
            self.after(0, self.master.destroy)

        threading.Thread(target=_run, daemon=True).start()


# ── Splash ───────────────────────────────────────────────────────────────────

def remove_borders(root):
    root.overrideredirect(True)
    os_name = platform.system()
    if os_name == "Windows":
        root.attributes("-toolwindow", True)
    elif os_name == "Darwin":
        try:
            root.tk.call('tk', 'unsupported', 'MacWindowStyle', 'style', root, 'none', 'none')
        except Exception:
            pass
        root.configure(bg="systemTransparent")
    elif os_name == "Linux":
        root.attributes("-type", "splash")
    root.configure(bd=0, highlightthickness=0)

def build_splash(root, width, height):
    bg = "white"
    if platform.system() == "Darwin":
        bg = "systemTransparent"
    try:
        img = Image.open("timon/app/static/img/timon_logo.png")
        img = img.resize((width, height), Image.LANCZOS)
        logo = ImageTk.PhotoImage(img)
        lbl = tk.Label(root, image=logo, bg=bg, bd=0, highlightthickness=0)
        lbl.image = logo
        lbl.place(x=0, y=0, width=width, height=height)
    except Exception:
        tk.Label(root, text="TIMON", font=("Arial", 40, "bold"), bg="white").pack(expand=True)

    tk.Label(root, text=get_software_version(),
             bg="white", fg="gray").place(x=10, y=height - 30)

    docker_ok    = check_docker_available()
    container_ok = check_container_preparation()
    status = f"docker: {'ON' if docker_ok else 'OFF'} | image: {'READY' if container_ok else 'MISSING'}"
    tk.Label(root, text=status, bg="white", font=("Arial", 9)).place(x=200, y=height - 30)


# ── Entry point ──────────────────────────────────────────────────────────────

def show_launcher(root):
    root.withdraw()
    LauncherWindow(root)

def start_app():
    root = tk.Tk()
    root.withdraw()
    remove_borders(root)

    W, H = 600, 370
    center_window(root, W, H)
    build_splash(root, W, H)

    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)

    if check_docker_available() and check_container_preparation():
        root.after(3000, lambda: show_launcher(root))
    else:
        root.after(5000, root.destroy)

    root.mainloop()

if __name__ == "__main__":
    start_app()
