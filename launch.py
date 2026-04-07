import os
import subprocess
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog
import platform
from PIL import Image, ImageTk


def run_main_app(root):
    root.withdraw()

    input_path = filedialog.askdirectory(title="Select FASTQ Directory")
    if not input_path:
        root.destroy()
        return

    input_path = os.path.abspath(input_path)
    output_path = os.path.join(input_path, "results")
    os.makedirs(output_path, exist_ok=True)

    docker_image = "timon:dev"
    cmd = [
        "docker", "run", "-d", "--rm",
        "-p", "8000:5000",
        "-v", f"{input_path}:/app/data",
        "-v", f"{output_path}:/app/results",
        "-e", "INPUT_DIR=/app/data",
        "-e", "OUTPUT_DIR=/app/results",
        docker_image
    ]

    print(f"Launching GUI... Mounting {input_path}")

    def open_browser():
        time.sleep(5)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=open_browser, daemon=True).start()
    subprocess.run(cmd)
    root.destroy()


def remove_borders(root):
    os_name = platform.system()
    if os_name == "Windows":
        root.attributes("-toolwindow", True)
        root.configure(bd=0, highlightthickness=0)
    elif os_name == "Darwin":
        root.attributes("-transparent", True)
        root.configure(bg="systemTransparent", bd=0, highlightthickness=0)
    elif os_name == "Linux":
        root.attributes("-type", "splash")
        root.configure(bd=0, highlightthickness=0)
    else:
        root.configure(bd=0, highlightthickness=0)


def build_splash(root, width, height):
    bg = "systemTransparent" if platform.system() == "Darwin" else "white"
    img = Image.open("timon/app/static/img/timon_logo.png")
    img = img.resize((width, height), Image.LANCZOS)
    logo = ImageTk.PhotoImage(img)
    lbl_logo = tk.Label(root, image=logo, bg=bg, bd=0, highlightthickness=0)
    lbl_logo.image = logo
    lbl_logo.place(x=0, y=0, width=width, height=height)


def start_app():
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    remove_borders(root)

    bg = "systemTransparent" if platform.system() == "Darwin" else "white"
    root.configure(bg=bg)

    WIDTH, HEIGHT = 600, 370

    build_splash(root, WIDTH, HEIGHT)

    root.update_idletasks()

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw // 2) - (WIDTH // 2)
    y = (sh // 2) - (HEIGHT // 2)
    root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)
    root.focus_force()

    root.after(5000, lambda: run_main_app(root))

    root.mainloop()


if __name__ == "__main__":
    start_app()
