"""Focused regression for the v53 settings NameError during model activation."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE))
import core


class SettingsActivationRegression(unittest.TestCase):
    def test_model_activation_writes_vision_metadata_from_the_selected_settings(self):
        name = core.HUIHUI_IQ3S_MODEL
        selected = {
            "model": name,
            "backend": "vulkan",
            "api_key": "fixture-only",
            "cpu_offload": False,
            "vision_gpu_offload": False,
            "kv_cache_type": "q4_0",
            "performance_mode": "standard",
            "speculative_type": "none",
        }
        with tempfile.TemporaryDirectory(dir=r"G:\LocalCodex-work\mycodex-repair-20261009\artifacts") as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            model = root / "model.gguf"
            projector = root / "mmproj.gguf"
            model.write_bytes(b"model fixture")
            projector.write_bytes(b"vision fixture")
            fake_proc = types.SimpleNamespace(pid=424242)
            with patch.object(core, "ROOT", root), \
                 patch.object(core, "selected_backend", return_value="vulkan"), \
                 patch.object(core, "ensure_backend_installed"), \
                 patch.object(core, "model_required_files", return_value=[model]), \
                 patch.object(core, "active_model", return_value={}), \
                 patch.object(core, "gpu_layers", return_value="all"), \
                 patch.object(core, "kv_cache_location", return_value="gpu"), \
                 patch.object(core, "selected_decoding", return_value="none"), \
                 patch.object(core, "chat_template_state", return_value={"policy": "fixture", "sha256": "abc", "file": None}), \
                 patch("emotion_vectors.emotion_state", return_value={"signature": "fixture", "mode": "off", "components": []}), \
                 patch.object(core, "reasoning_budget", return_value=4096), \
                 patch.object(core, "configured_vision", return_value=True), \
                 patch.object(core, "active_model_supports_vision", return_value=False), \
                 patch.object(core, "server_ready", return_value=False), \
                 patch.object(core, "ensure_full_gpu_capacity"), \
                 patch.object(core, "model_args", return_value=["fixture-engine"]), \
                 patch.object(core, "model_file", return_value=model), \
                 patch.object(core, "vision_file", return_value=projector), \
                 patch.object(core.subprocess, "Popen", return_value=fake_proc):
                core._start_model(name, 40960, False, 40960, selected)

            active = json.loads((root / "active-model.json").read_text(encoding="utf-8"))
            self.assertEqual(active["model"], name)
            self.assertEqual(active["vision_projector"], str(projector))
            self.assertFalse(active["vision_gpu_offload"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
