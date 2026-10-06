"""Tests for GPU detection (sunak/gpu.py) with simulated tool output, sysfs trees and registry."""

import os
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

from sunak import gpu, ollama
from sunak.__main__ import gpu_report
from sunak.server import recommend


class ParseTest(unittest.TestCase):
    def test_nvidia_smi(self):
        out = "NVIDIA GeForce RTX 4070, 12282\nNVIDIA RTX A2000, Ada, 6138\n\ngarbage\n"
        gpus = gpu.parse_nvidia_smi(out)
        self.assertEqual([(g["name"], g["vram_gb"], g["usable"]) for g in gpus],
                         [("NVIDIA GeForce RTX 4070", 12.0, True), ("NVIDIA RTX A2000, Ada", 6.0, True)])
        self.assertEqual(gpu.parse_nvidia_smi(None), [])

    def test_nvidia_smi_missing_or_failing(self):
        with unittest.mock.patch("shutil.which", return_value=None), \
                unittest.mock.patch("platform.system", return_value="Linux"):
            self.assertEqual(gpu.nvidia_smi(), [])
        with unittest.mock.patch("shutil.which", return_value="/usr/bin/nvidia-smi"), \
                unittest.mock.patch("subprocess.run", side_effect=OSError("boom")):
            self.assertEqual(gpu.nvidia_smi(), [])

    def test_linux_sysfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "drm"
            drivers = Path(tmp) / "drivers"

            def card(name, vendor, driver=None, **files):
                dev = root / name / "device"
                dev.mkdir(parents=True)
                (dev / "vendor").write_text(vendor + "\n")
                for k, v in files.items():
                    (dev / k).write_text(v + "\n")
                if driver:
                    (drivers / driver).mkdir(parents=True, exist_ok=True)
                    try:
                        (dev / "driver").symlink_to(drivers / driver)
                    except OSError:
                        self.skipTest("no symlinks here")

            card("card0", "0x1002", "amdgpu", mem_info_vram_total=str(16 * 1024**3), product_name="Radeon RX 7800 XT")
            card("card1", "0x10de", "nouveau")
            card("card2", "0x8086", "i915")
            card("card3", "0x1002", "amdgpu", mem_info_vram_total=str(512 * 1024**2))  # APU carve-out
            (root / "card0-HDMI-A-1").mkdir()
            gpus = gpu.linux_sysfs(root)
        self.assertEqual([(g["vendor"], g["name"], g["vram_gb"], g["driver"], g["usable"]) for g in gpus], [
            ("amd", "Radeon RX 7800 XT", 16.0, True, True),
            ("nvidia", "NVIDIA GPU", None, False, False),
            ("intel", "Intel GPU", None, True, False),
            ("amd", "AMD GPU", 0.5, True, False),
        ])
        info = gpu.summary(gpus)
        self.assertEqual((info["usable"], info["vendor"], info["vram_gb"], info["hint"]), (True, "amd", 16.0, None))
        info = gpu.summary(gpus[1:])  # only the NVIDIA card without driver is left that could work
        self.assertFalse(info["usable"])
        self.assertIn("driver", info["hint"])

    def test_windows_registry(self):
        keys = {
            "0000": {"DriverDesc": "NVIDIA GeForce RTX 3060", "HardwareInformation.qwMemorySize": 12 * 1024**3},
            "0001": {"DriverDesc": "AMD Radeon(TM) Graphics", "HardwareInformation.MemorySize": (512 * 1024**2).to_bytes(4, "little")},
            "0002": {"DriverDesc": "Microsoft Basic Display Adapter"},
            "0003": None,  # "Properties": access denied
        }

        class Key:
            def __init__(self, name):
                self.name = name

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def open_key(parent, sub):
            if isinstance(parent, Key) and keys.get(sub) is None:
                raise PermissionError(sub)
            return Key(sub)

        def enum_key(k, i):
            if i >= len(keys):
                raise OSError("no more")
            return list(keys)[i]

        def query(k, value):
            if value not in keys[k.name]:
                raise FileNotFoundError(value)
            return keys[k.name][value], 0

        fake = types.SimpleNamespace(HKEY_LOCAL_MACHINE=object(), OpenKey=open_key, EnumKey=enum_key, QueryValueEx=query)
        with unittest.mock.patch.dict(sys.modules, {"winreg": fake}):
            gpus = gpu.windows_registry()
        self.assertEqual([(g["vendor"], g["vram_gb"], g["usable"]) for g in gpus],
                         [("nvidia", 12.0, True), ("amd", 0.5, False)])

    def test_detect_prefers_nvidia_smi(self):
        sysfs = [gpu._gpu("nvidia", "NVIDIA GPU", driver=False), gpu._gpu("intel", "Intel GPU")]
        smi = [gpu._gpu("nvidia", "RTX 4090", 24.0)]
        with unittest.mock.patch("platform.system", return_value="Linux"), \
                unittest.mock.patch.object(gpu, "nvidia_smi", return_value=smi), \
                unittest.mock.patch.object(gpu, "linux_sysfs", return_value=sysfs):
            self.assertEqual([g["name"] for g in gpu.detect()], ["RTX 4090", "Intel GPU"])
            self.assertEqual(gpu.summary(gpu.detect())["vram_gb"], 24.0)

    def test_apple_silicon(self):
        with unittest.mock.patch("platform.system", return_value="Darwin"), \
                unittest.mock.patch("platform.machine", return_value="arm64"), \
                unittest.mock.patch.object(gpu, "_run", return_value="Apple M3 Pro\n"):
            info = gpu.summary(gpu.detect())
        self.assertEqual((info["vendor"], info["unified"], info["usable"], info["gpus"][0]["name"]),
                         ("apple", True, True, "Apple M3 Pro"))
        with unittest.mock.patch("platform.system", return_value="Darwin"), \
                unittest.mock.patch("platform.machine", return_value="x86_64"), \
                unittest.mock.patch.object(gpu, "_run", return_value="0\n"):
            self.assertEqual(gpu.detect(), [])  # Ollama does not use the GPU of Intel Macs


class UseTest(unittest.TestCase):
    NVIDIA = gpu.summary([gpu._gpu("nvidia", "RTX 4070", 12.0)])

    def test_loaded_info(self):
        loaded = gpu.loaded_info([{"name": "a", "size": 100, "size_vram": 100}, {"name": "b", "size": 100, "size_vram": 62},
                                  {"name": "c", "size": 100, "size_vram": 0}, {"name": "d"}])
        self.assertEqual([m["gpu_pct"] for m in loaded], [100, 62, 0, 0])

    def test_cpu_warning(self):
        cpu = gpu.loaded_info([{"name": "a", "size": 100, "size_vram": 0}])
        on_gpu = gpu.loaded_info([{"name": "a", "size": 100, "size_vram": 40}])
        self.assertIn("NVIDIA Container Toolkit", gpu.cpu_warning(self.NVIDIA, cpu))
        self.assertIsNone(gpu.cpu_warning(self.NVIDIA, on_gpu))
        self.assertIsNone(gpu.cpu_warning(self.NVIDIA, []))           # nothing loaded: unknown
        self.assertIsNone(gpu.cpu_warning(gpu.summary([]), cpu))      # no GPU: CPU is expected
        self.assertIn("docker-compose.amd.yml", gpu.cpu_warning(None, cpu, docker_vendor="amd"))
        apple = gpu.summary([gpu._gpu("apple", "Apple M2", unified=True)])
        self.assertIn("Docker", gpu.cpu_warning(apple, cpu))

    def test_expected_from_docker(self):
        with unittest.mock.patch.dict(os.environ, {"SUNAK_GPU": "NVIDIA"}):
            self.assertEqual(gpu.expected(), "nvidia")
        with unittest.mock.patch.dict(os.environ, {"SUNAK_GPU": "cpu"}):
            self.assertIsNone(gpu.expected())

    def test_catalog_and_recommendation(self):
        cat = {m["name"]: m for m in ollama.catalog(16, self.NVIDIA)}
        self.assertTrue(cat["qwen3:8b"]["gpu"] and cat["qwen3:8b"]["fits"])
        self.assertFalse(cat["qwen3:14b"]["gpu"])                     # 9.3 GB needs 12.2 GB VRAM
        self.assertFalse(any(m["gpu"] for m in ollama.catalog(16)))
        apple = gpu.summary([gpu._gpu("apple", "Apple M2", unified=True)])
        self.assertTrue(all(m["gpu"] == m["fits"] for m in ollama.catalog(16, apple)))
        self.assertEqual(recommend(8)["model"], "qwen3:4b")
        self.assertEqual(recommend(8, self.NVIDIA)["model"], "qwen3:8b")   # bigger, because it fits the VRAM
        self.assertEqual(recommend(32, gpu.summary([gpu._gpu("nvidia", "small", 4.0)]))["model"], "qwen3:14b")  # never smaller

    def test_report_names_the_best_gpu(self):
        info = gpu.summary(gpu.parse_nvidia_smi("GTX 1060 6GB, 6144\nRTX 4090, 24564"))
        self.assertEqual(info["name"], "RTX 4090")
        self.assertIn("RTX 4090 (24.0 GB VRAM)", gpu_report(info)[0])

    def test_apple_silicon_under_rosetta(self):
        with unittest.mock.patch("platform.system", return_value="Darwin"), \
                unittest.mock.patch("platform.machine", return_value="x86_64"), \
                unittest.mock.patch.object(gpu, "_run", side_effect=lambda cmd, **k: "1\n" if "hw.optional.arm64" in cmd else "Apple M1\n"):
            self.assertEqual(gpu.detect()[0]["vendor"], "apple")

    def test_report(self):
        self.assertIn("RTX 4070 (12.0 GB VRAM)", gpu_report(self.NVIDIA)[0])
        self.assertIn("No GPU", gpu_report(gpu.summary([]))[0])
        self.assertIn("driver", gpu_report(gpu.summary([gpu._gpu("nvidia", "NVIDIA GPU", driver=False)]))[0])
        self.assertIn("Metal", gpu_report(gpu.summary([gpu._gpu("apple", "Apple M1", unified=True)]))[0])


if __name__ == "__main__":
    unittest.main()
