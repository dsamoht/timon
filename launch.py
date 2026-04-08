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


def get_software_version():
    with open("environment.yaml", "r") as env_file:
        for line in env_file:
            if line.startswith("name: timon_"):
                return line.split("name: timon_")[1].strip()
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
        result = subprocess.run(
            ["docker", "image", "ls", "-q", "timon:dev"],
            capture_output=True, text=True, timeout=5
        )
        return bool(result.stdout.strip())
    except:
        return False

def check_docker_available():
    try:
        result = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        return result.returncode == 0
    except:
        return False

def run_docker_logic(input_path, root):
    input_path = os.path.abspath(input_path)
    output_path = os.path.join(input_path, "results")
    os.makedirs(output_path, exist_ok=True)

    docker_image = "timon:dev"
    cmd = [
        "docker", "run", "-d", "--rm",
        "-p", f"{host_port}:8000",
        "-v", f"{input_path}:/app/data",
        "-v", f"{output_path}:/app/results",
        "-e", "INPUT_DIR=/app/data",
        "-e", "OUTPUT_DIR=/app/results",
        docker_image
    ]

    subprocess.run(cmd)
    
    time.sleep(5)
    webbrowser.open(f"http://localhost:{host_port}")
    
    root.after(0, root.destroy)

def start_pipeline(root):
    root.withdraw()
    input_path = filedialog.askdirectory(title="Select FASTQ Directory")
    
    if not input_path:
        root.destroy()
        return

    threading.Thread(target=run_docker_logic, args=(input_path, root), daemon=True).start()


def remove_borders(root):
    """Removes window decorations based on OS."""
    root.overrideredirect(True)
    os_name = platform.system()
    
    if os_name == "Windows":
        root.attributes("-toolwindow", True)
    elif os_name == "Darwin":
        try:
            root.tk.call('tk', 'unsupported', 'MacWindowStyle', 'style', root, 'none', 'none')
        except:
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
        lbl_logo = tk.Label(root, image=logo, bg=bg, bd=0, highlightthickness=0)
        lbl_logo.image = logo
        lbl_logo.place(x=0, y=0, width=width, height=height)
    except Exception:
        tk.Label(root, text="TIMON", font=("Arial", 40, "bold"), bg="white").pack(expand=True)

    # Version label
    tk.Label(root, text=f"{get_software_version()}", bg="white", fg="gray").place(x=10, y=height-30)
    
    # Check Status
    docker_ok = check_docker_available()
    container_ok = check_container_preparation()
    
    status_text = f"docker: {'ON' if docker_ok else 'OFF'} | image: {'READY' if container_ok else 'MISSING'}"
    tk.Label(root, text=status_text, bg="white", font=("Arial", 9)).place(x=200, y=height-30)

def start_app():
    root = tk.Tk()
    root.withdraw()
    remove_borders(root)

    WIDTH, HEIGHT = 600, 370
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - (WIDTH // 2)
    y = (root.winfo_screenheight() // 2) - (HEIGHT // 2)
    root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")
    
    build_splash(root, WIDTH, HEIGHT)
    
    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)

    if check_docker_available() and check_container_preparation():
        root.after(3000, lambda: start_pipeline(root))
    else:
        root.after(5000, root.destroy)

    root.mainloop()

if __name__ == "__main__":
    start_app()
