import ctypes
import os
import socket
import struct
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
os.makedirs("logs", exist_ok=True)
os.makedirs("ctl", exist_ok=True)

stop_event = threading.Event()


def wsl_base_cmd():
    vhdx = os.path.join(ROOT, "third_party", "wsl-distro", "instance", "ext4.vhdx")
    if os.path.exists(vhdx):
        return ["wsl", "-d", "ew3-wsl"]
    return ["wsl"]


def has_wsl_qemu_arm():
    if os.environ.get("EW3_FORCE_QEMU_SYSTEM", "") == "1":
        return False
    vhdx = os.path.join(ROOT, "third_party", "wsl-distro", "instance", "ext4.vhdx")
    if os.path.exists(vhdx):
        return True
    try:
        r = subprocess.run(
            ["wsl", "-e", "sh", "-c", "command -v qemu-arm >/dev/null 2>&1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def to_wsl_path(win_path):
    p = os.path.abspath(win_path).replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        return f"/mnt/{p[0].lower()}{p[2:]}"
    return p


def ensure_build(use_wsl=False):
    import glob

    py = os.path.join(ROOT, "server", ".venv", "Scripts", "python.exe")
    zig = os.path.join(ROOT, "third_party", "zig", "zig.exe")

    ew3gl_exe = os.path.join(ROOT, "host", "build-win", "ew3gl.exe")
    gl_srcs = glob.glob(os.path.join(ROOT, "host", "glbridge", "*.c")) + glob.glob(
        os.path.join(ROOT, "host", "glbridge", "*.inc")
    )
    if not os.path.exists(ew3gl_exe) or any(
        os.path.getmtime(s) > os.path.getmtime(ew3gl_exe) for s in gl_srcs
    ):
        print("[launcher] rebuilding host/build-win/ew3gl.exe...")
        os.makedirs(os.path.join(ROOT, "host", "build-win"), exist_ok=True)
        subprocess.run(
            [
                zig,
                "cc",
                "-target",
                "x86_64-windows-gnu",
                "-O2",
                "-DSDL_MAIN_HANDLED",
                "-Ihost/glbridge",
                "-Ithird_party/khronos/include",
                "-Ithird_party/sdl2-win/include",
                "-Ithird_party/sdl2-win/include/SDL2",
                "host/glbridge/ew3gl.c",
                "third_party/sdl2-win/lib/SDL2.lib",
                "host/build-win/libGLESv2.lib",
                "-lws2_32",
                "-o",
                ew3gl_exe,
            ],
            check=True,
        )

    wsl_runner_src = os.path.join(ROOT, "third_party", "qemu-guest", "wsl_runner.c")
    wsl_runner_bin = os.path.join(ROOT, "third_party", "qemu-guest", "wsl_runner")
    if os.path.exists(wsl_runner_src) and (
        not os.path.exists(wsl_runner_bin)
        or os.path.getmtime(wsl_runner_src) > os.path.getmtime(wsl_runner_bin)
    ):
        print("[launcher] building third_party/qemu-guest/wsl_runner...")
        subprocess.run(
            [
                zig,
                "cc",
                "-target",
                "x86_64-linux-musl",
                "-static",
                "-O2",
                wsl_runner_src,
                "-o",
                wsl_runner_bin,
                "-lpthread",
            ],
            check=True,
        )

    from tools.build_port import build_all

    port_rebuilt = build_all()

    if use_wsl:
        return

    initrd_path = os.path.join(ROOT, "third_party", "qemu-guest", "ew3_initrd.cpio")
    initrd_deps = [
        os.path.join(ROOT, "port", "build", "ew3"),
        os.path.join(ROOT, "sdl-arm", "lib", "libSDL2-2.0.so.0"),
        os.path.join(ROOT, "third_party", "qemu-guest", "runner.c"),
        os.path.join(ROOT, "third_party", "qemu-guest", "build_initrd.py"),
    ]
    if (
        port_rebuilt
        or not os.path.exists(initrd_path)
        or any(os.path.getmtime(d) > os.path.getmtime(initrd_path) for d in initrd_deps)
    ):
        print("[launcher] repacking guest initramfs...")
        subprocess.run(
            [py, os.path.join(ROOT, "third_party", "qemu-guest", "build_initrd.py")],
            check=True,
        )


def port_open(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def ensure_server():
    import glob

    pid_file = os.path.join(ROOT, "logs", "server.pid")
    srv_srcs = glob.glob(os.path.join(ROOT, "server", "*.py"))
    if port_open(18080):
        need_restart = not os.path.exists(pid_file) or any(
            os.path.getmtime(s) > os.path.getmtime(pid_file) for s in srv_srcs
        )
        if not need_restart:
            print("[launcher] ew3server is already running on :18080")
            return None
        print("[launcher] restarting ew3server.py to pick up server changes...")
        if os.path.exists(pid_file):
            try:
                old_pid = int(open(pid_file).read().strip())
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(old_pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
        time.sleep(0.5)
    print("[launcher] starting ew3server.py...")
    py = os.path.join(ROOT, "server", ".venv", "Scripts", "python.exe")
    log_f = open(os.path.join(ROOT, "logs", "server.log"), "a", encoding="utf-8")
    proc = subprocess.Popen(
        [py, os.path.join(ROOT, "server", "ew3server.py")],
        stdout=log_f,
        stderr=subprocess.STDOUT,
    )
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))
    for _ in range(50):
        if port_open(18080):
            print("[launcher] ew3server ready on :18080 and :18024")
            return proc
        time.sleep(0.2)
    print("[launcher] WARNING: ew3server did not bind :18080 in time")
    return proc


GUEST_HOSTS = ["127.0.0.1"]
CONNECTED_HOST = "127.0.0.1"
mux_connected = threading.Event()


def connect_retry(port):
    global CONNECTED_HOST
    while not stop_event.is_set():
        for h in list(GUEST_HOSTS):
            try:
                s = socket.create_connection((h, port), timeout=0.5)
                s.settimeout(None)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                CONNECTED_HOST = h
                if port == 18092:
                    mux_connected.set()
                return s
            except OSError:
                pass
        time.sleep(0.1)
    return None


def ctl_relay_worker(cmd_file):
    s = connect_retry(18091)
    if not s:
        return
    with open(cmd_file, "rb") as f:
        while not stop_event.is_set():
            data = f.read()
            if data:
                try:
                    s.sendall(data)
                except OSError:
                    break
            else:
                time.sleep(0.001)
    try:
        s.close()
    except OSError:
        pass


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def net_mux_worker():
    mux_sock = connect_retry(18092)
    if not mux_sock:
        return
    mux_lock = threading.Lock()
    conns = {}

    def send_mux(cid, cmd, payload=b""):
        hdr = struct.pack("<IHH", cid, cmd, len(payload))
        with mux_lock:
            try:
                mux_sock.sendall(hdr + payload)
            except OSError:
                pass

    def backend_reader(cid, bsock):
        try:
            while not stop_event.is_set():
                data = bsock.recv(16384)
                if not data:
                    break
                send_mux(cid, 2, data)
        except OSError:
            pass
        finally:
            send_mux(cid, 3, b"")
            conns.pop(cid, None)
            try:
                bsock.close()
            except OSError:
                pass

    while not stop_event.is_set():
        hdr = recv_exact(mux_sock, 8)
        if not hdr:
            break
        cid, cmd, dlen = struct.unpack("<IHH", hdr)
        if cmd == 1:
            port = dlen
            try:
                bsock = socket.create_connection(("127.0.0.1", port), timeout=2.0)
                bsock.settimeout(None)
                bsock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conns[cid] = bsock
                t = threading.Thread(target=backend_reader, args=(cid, bsock), daemon=True)
                t.start()
            except OSError:
                send_mux(cid, 3, b"")
        elif cmd == 2:
            payload = recv_exact(mux_sock, dlen) if dlen > 0 else b""
            if payload is None:
                break
            bsock = conns.get(cid)
            if bsock:
                try:
                    bsock.sendall(payload)
                except OSError:
                    conns.pop(cid, None)
                    try:
                        bsock.close()
                    except OSError:
                        pass
        elif cmd == 3:
            bsock = conns.pop(cid, None)
            if bsock:
                try:
                    bsock.close()
                except OSError:
                    pass


class SDL_AudioSpec(ctypes.Structure):
    _fields_ = [
        ("freq", ctypes.c_int),
        ("format", ctypes.c_uint16),
        ("channels", ctypes.c_uint8),
        ("silence", ctypes.c_uint8),
        ("samples", ctypes.c_uint16),
        ("padding", ctypes.c_uint16),
        ("size", ctypes.c_uint32),
        ("callback", ctypes.c_void_p),
        ("userdata", ctypes.c_void_p),
    ]


def audio_worker():
    s = connect_retry(18093)
    if not s:
        return
    try:
        sdl = ctypes.CDLL(os.path.join(ROOT, "host", "build-win", "SDL2.dll"))
        sdl.SDL_InitSubSystem(0x00000010)  # SDL_INIT_AUDIO
        dev_id = 0
        cur_freq = 0
        while not stop_event.is_set():
            hdr = recv_exact(s, 12)
            if not hdr:
                break
            magic, freq, dlen = struct.unpack("<III", hdr)
            if magic != 0x41335745 or dlen > 65536:
                break
            pcm = recv_exact(s, dlen)
            if not pcm:
                break
            if freq != cur_freq and freq > 0:
                if dev_id:
                    sdl.SDL_CloseAudioDevice(dev_id)
                want = SDL_AudioSpec()
                obtained = SDL_AudioSpec()
                want.freq = freq
                want.format = 0x8010  # AUDIO_S16LSB
                want.channels = 2
                want.samples = 1024
                sdl.SDL_OpenAudioDevice.restype = ctypes.c_uint32
                dev_id = sdl.SDL_OpenAudioDevice(
                    None, 0, ctypes.byref(want), ctypes.byref(obtained), 0
                )
                if dev_id:
                    sdl.SDL_PauseAudioDevice(dev_id, 0)
                    cur_freq = freq
            if dev_id:
                sdl.SDL_QueueAudio(dev_id, pcm, dlen)
    except Exception as e:
        print(f"[audio] note: {e}")


def cleanup_old_session(use_wsl=False):
    for proc_name in ("ew3gl.exe", "qemu-system-arm.exe"):
        subprocess.run(
            ["taskkill", "/F", "/IM", proc_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if use_wsl:
        subprocess.run(
            wsl_base_cmd() + ["-e", "sh", "-c", "pkill -9 -f wsl_runner 2>/dev/null; pkill -9 -f '/opt/ew3_rt/app/ew3' 2>/dev/null; true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    time.sleep(0.3)


def start_wsl_guest(w, h, play_log):
    try:
        ip_out = subprocess.check_output(
            wsl_base_cmd() + ["-e", "sh", "-c", "ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i==\"src\") print $(i+1)}'"],
            text=True,
            timeout=15,
        ).strip().split()
        if ip_out and ip_out[0] not in GUEST_HOSTS:
            GUEST_HOSTS.append(ip_out[0])
    except Exception:
        pass

    wsl_root = to_wsl_path(ROOT)
    start_sh = os.path.join(ROOT, "third_party", "qemu-guest", "start_wsl.sh")
    with open(start_sh, "wb") as sf:
        sf.write(
            b"#!/bin/sh\n"
            b'cp -f "$1/third_party/qemu-guest/wsl_runner" /tmp/wsl_runner\n'
            b"chmod +x /tmp/wsl_runner\n"
            b'exec /tmp/wsl_runner "$1" "$2" "$3"\n'
        )
    wsl_cmd = wsl_base_cmd() + [
        "-e",
        "sh",
        f"{wsl_root}/third_party/qemu-guest/start_wsl.sh",
        wsl_root,
        str(w),
        str(h),
    ]
    print("[launcher] starting ARM32 guest via WSL2 qemu-arm (user-mode, fast)...")
    return subprocess.Popen(
        wsl_cmd,
        stdin=subprocess.DEVNULL,
        stdout=play_log,
        stderr=subprocess.STDOUT,
    )


def main():
    res = sys.argv[1] if len(sys.argv) > 1 else "1280x720"
    w, h = res.split("x")
    use_wsl = has_wsl_qemu_arm()
    cleanup_old_session(use_wsl=use_wsl)
    ensure_build(use_wsl=use_wsl)
    ensure_server()

    cmd_file = os.path.join(ROOT, "ctl", "commands")
    with open(cmd_file, "wb"):
        pass

    play_log_path = os.path.join(ROOT, "logs", "play.log")
    play_log = open(play_log_path, "w", encoding="utf-8")

    if use_wsl:
        guest_proc = start_wsl_guest(w, h, play_log)
    else:
        qemu_exe = os.path.join(
            ROOT, "third_party", "qemu", "xpack-qemu-arm-9.2.4-1", "bin", "qemu-system-arm.exe"
        )
        gpu_arg = os.environ.get("EW3_GPU", "").strip().replace(" ", "_")
        append_str = f"console=ttyAMA0 raid=noautodetect quiet ew3_w={w} ew3_h={h}"
        if gpu_arg:
            append_str += f" ew3_gpu={gpu_arg}"

        qemu_cmd = [
            qemu_exe,
            "-M",
            "virt,highmem=off",
            "-accel",
            "tcg,thread=multi,tb-size=1024",
            "-cpu",
            "cortex-a15",
            "-smp",
            "4",
            "-m",
            "2048",
            "-nographic",
            "-kernel",
            os.path.join(ROOT, "third_party", "qemu-guest", "vmlinuz"),
            "-initrd",
            os.path.join(ROOT, "third_party", "qemu-guest", "ew3_initrd.cpio"),
            "-device",
            "virtio-serial-device",
            "-chardev",
            "socket,id=ch1,host=127.0.0.1,port=18090,server=on,wait=off,nodelay=on",
            "-device",
            "virtserialport,chardev=ch1,name=p1",
            "-chardev",
            "socket,id=ch2,host=127.0.0.1,port=18091,server=on,wait=off,nodelay=on",
            "-device",
            "virtserialport,chardev=ch2,name=p2",
            "-chardev",
            "socket,id=ch3,host=127.0.0.1,port=18092,server=on,wait=off,nodelay=on",
            "-device",
            "virtserialport,chardev=ch3,name=p3",
            "-chardev",
            "socket,id=ch4,host=127.0.0.1,port=18093,server=on,wait=off,nodelay=on",
            "-device",
            "virtserialport,chardev=ch4,name=p4",
            "-append",
            append_str,
        ]
        print("[launcher] starting ARM32 guest VM (qemu-system-arm fallback)...")
        guest_proc = subprocess.Popen(
            qemu_cmd,
            stdin=subprocess.DEVNULL,
            stdout=play_log,
            stderr=subprocess.STDOUT,
        )

    threading.Thread(target=ctl_relay_worker, args=(cmd_file,), daemon=True).start()
    threading.Thread(target=net_mux_worker, daemon=True).start()
    threading.Thread(target=audio_worker, daemon=True).start()

    mux_connected.wait(timeout=10.0)

    env = os.environ.copy()
    env["EW3_GL_CONNECT"] = f"{CONNECTED_HOST}:18090"
    env["EW3_WIDTH"] = w
    env["EW3_HEIGHT"] = h
    env["EW3_CONTROL_DIR"] = os.path.join(ROOT, "ctl")
    env["EW3_GL_LOG"] = os.path.join(ROOT, "logs", "ew3gl.log")
    env["EW3_GL_VSYNC"] = env.get("EW3_GL_VSYNC", "0")

    ew3gl_exe = os.path.join(ROOT, "host", "build-win", "ew3gl.exe")
    print("[launcher] starting ew3gl.exe window...")
    gl_proc = subprocess.Popen([ew3gl_exe], env=env)

    try:
        gl_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        if gl_proc.poll() is None:
            gl_proc.terminate()
        if guest_proc.poll() is None:
            guest_proc.terminate()
            try:
                guest_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                guest_proc.kill()
        if use_wsl:
            subprocess.run(
                wsl_base_cmd() + ["-e", "sh", "-c", "pkill -9 -f wsl_runner 2>/dev/null; pkill -9 -f '/opt/ew3_rt/app/ew3' 2>/dev/null; true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        play_log.close()
        print("[launcher] game session ended.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        err = traceback.format_exc()
        print(err, file=sys.stderr)
        with open(os.path.join(ROOT, "logs", "launcher.log"), "w", encoding="utf-8") as f:
            f.write(err)
        sys.exit(1)

