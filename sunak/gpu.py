"""GPU detection. Sunak itself does not compute anything; Ollama runs the models and uses a GPU on
its own (CUDA for NVIDIA, ROCm for AMD, Metal on Apple Silicon). This module finds out which GPU
the computer has, so the app can recommend models that fit into its memory and warn when Ollama
runs on the CPU although a GPU is there. Standard library only; every probe fails quietly."""

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

VENDORS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}
MIN_VRAM_GB = 3  # less is an integrated GPU with a small memory carve-out: Ollama does not use it
SKIP = re.compile(r"microsoft basic|remote|virtual|hyper-v|parsec|vmware|virtualbox|citrix", re.I)


def _run(cmd, timeout=6):
    """stdout of a command, or None when it is missing or fails."""
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, **kwargs)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _gpu(vendor, name, vram_gb=None, driver=True, unified=False):
    usable = driver and (unified or (vendor in ("nvidia", "amd") and (vram_gb or 0) >= MIN_VRAM_GB))
    return {"vendor": vendor, "name": name, "vram_gb": vram_gb, "driver": driver, "unified": unified,
            "usable": bool(usable)}


def parse_nvidia_smi(out):
    """GPUs from `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits`."""
    gpus = []
    for line in (out or "").splitlines():
        name, _, mib = line.rpartition(",")
        if name.strip() and mib.strip().isdigit():
            gpus.append(_gpu("nvidia", name.strip(), round(int(mib) / 1024, 1)))
    return gpus


def nvidia_smi():
    """NVIDIA GPUs as the driver reports them ([] without driver)."""
    exe = shutil.which("nvidia-smi")
    if not exe and platform.system() == "Windows":
        exe = next((p for p in (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
                                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe")
                    if p.is_file()), None)
    if not exe:
        return []
    return parse_nvidia_smi(_run([str(exe), "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]))


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def linux_sysfs(root="/sys/class/drm"):
    """GPUs from /sys/class/drm (works without any tool; VRAM is known for AMD)."""
    gpus = []
    for card in sorted(Path(root).glob("card[0-9]*")):
        if "-" in card.name:  # card0-HDMI-A-1 is a connector, not a GPU
            continue
        dev = card / "device"
        vendor = VENDORS.get(_read(dev / "vendor").lower())
        if not vendor:
            continue
        vram = _read(dev / "mem_info_vram_total")
        vram_gb = round(int(vram) / 1024**3, 1) if vram.isdigit() else None
        try:
            driver = (dev / "driver").resolve().name
        except OSError:
            driver = ""
        name = _read(dev / "product_name") or {"nvidia": "NVIDIA GPU", "amd": "AMD GPU", "intel": "Intel GPU"}[vendor]
        # an NVIDIA card only works for Ollama with NVIDIA's own driver (not nouveau)
        gpus.append(_gpu(vendor, name, vram_gb, driver=driver != "nouveau" and (vendor != "nvidia" or driver == "nvidia")))
    return gpus


def windows_registry():
    """GPUs from the Windows registry (display adapter class), with their dedicated memory."""
    try:
        import winreg
    except ImportError:
        return []
    gpus = []
    path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        cls = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError:
        return []
    with cls:
        for i in range(64):
            try:
                sub = winreg.EnumKey(cls, i)
            except OSError:
                break
            try:
                with winreg.OpenKey(cls, sub) as k:
                    desc = str(winreg.QueryValueEx(k, "DriverDesc")[0])
                    size = None
                    for value in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                        try:
                            raw = winreg.QueryValueEx(k, value)[0]
                        except OSError:
                            continue
                        size = int.from_bytes(raw[:8], "little") if isinstance(raw, bytes) else int(raw)
                        break
            except (OSError, ValueError, TypeError):
                continue
            if SKIP.search(desc):
                continue
            low = desc.lower()
            vendor = "nvidia" if "nvidia" in low else "amd" if ("amd" in low or "radeon" in low) else \
                "intel" if "intel" in low else None
            if vendor:
                gpus.append(_gpu(vendor, desc, round(size / 1024**3, 1) if size else None))
    return gpus


def apple():
    """Apple Silicon: the GPU shares the main memory and Ollama uses it through Metal."""
    if platform.system() != "Darwin":
        return []
    # Python running under Rosetta reports x86_64, the hardware still is Apple Silicon
    if platform.machine() != "arm64" and (_run(["sysctl", "-n", "hw.optional.arm64"]) or "").strip() != "1":
        return []
    name = (_run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "").strip() or "Apple Silicon"
    return [_gpu("apple", name, unified=True)]


def detect():
    """All GPUs of this computer: [{vendor, name, vram_gb, driver, unified, usable}]."""
    system = platform.system()
    if system == "Darwin":
        return apple()
    nvidia = nvidia_smi()
    if system == "Windows":
        other = windows_registry()
    elif system == "Linux":
        other = linux_sysfs()
    else:
        other = []
    if nvidia:  # the driver knows NVIDIA cards best
        other = [g for g in other if g["vendor"] != "nvidia"]
    return nvidia + other


def summary(gpus):
    """What the app needs: the GPUs, whether Ollama can use one, and its memory."""
    usable = [g for g in gpus if g["usable"]]
    best = max(usable, key=lambda g: (g["unified"], g["vram_gb"] or 0), default=None)
    hint = None
    if not usable and any(g["vendor"] == "nvidia" and not g["driver"] for g in gpus):
        hint = ("An NVIDIA GPU was found, but its driver is missing. Install the NVIDIA driver "
                "(nvidia-smi must work), then restart Ollama, so it can use the GPU.")
    return {"gpus": gpus, "usable": bool(best), "vendor": best["vendor"] if best else None,
            "name": best["name"] if best else None,
            "vram_gb": best["vram_gb"] if best else None, "unified": bool(best and best["unified"]), "hint": hint}


def expected():
    """GPU vendor the Docker setup was started for (SUNAK_GPU=nvidia|amd), else None."""
    v = os.environ.get("SUNAK_GPU", "").strip().lower()
    return v if v in ("nvidia", "amd") else None


def loaded_info(models):
    """Models Ollama has in memory (/api/ps) with the share that sits on the GPU."""
    out = []
    for m in models:
        size, vram = m.get("size") or 0, m.get("size_vram") or 0
        pct = 100 if size and vram >= size else round(100 * vram / size) if size else 0
        out.append({"name": m.get("name", ""), "size": size, "size_vram": vram, "gpu_pct": pct})
    return out


def cpu_warning(info, loaded, docker_vendor=None):
    """Help text when a GPU is there but Ollama runs the loaded models on the CPU, else None."""
    if not loaded or any(m["size_vram"] > 0 for m in loaded):
        return None
    vendor = docker_vendor or (info["vendor"] if info and info["usable"] else None)
    if vendor == "nvidia":
        return ("Ollama runs on the CPU although an NVIDIA GPU is there. Update the NVIDIA driver and restart "
                "Ollama. With Docker: install the NVIDIA Container Toolkit and start with docker-compose.gpu.yml.")
    if vendor == "amd":
        return ("Ollama runs on the CPU although an AMD GPU is there. Ollama needs ROCm support for the card "
                "(see ollama.com/blog/amd-preview); some cards work with HSA_OVERRIDE_GFX_VERSION. "
                "With Docker: start with docker-compose.amd.yml.")
    if vendor == "apple":
        return ("Ollama runs on the CPU. On a Mac Ollama uses the GPU only when it runs as the normal Ollama app, "
                "not inside Docker.")
    return None
