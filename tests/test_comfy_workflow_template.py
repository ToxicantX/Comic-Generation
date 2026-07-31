import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "comfy_workflow_template.py"


def load_module():
    spec = importlib.util.spec_from_file_location("comfy_workflow_template", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(module, **overrides):
    values = {
        "prompt": "hero crossing a mountain pass",
        "negative_prompt": "text, watermark",
        "filename_prefix": "ComicPipeline/panels/episode01_panel01_v001",
        "checkpoint": "comic-model.safetensors",
        "image_size": "1024x1536",
        "seed": 42,
    }
    values.update(overrides)
    return module.build_local_image_workflow(**values)


class ComfyWorkflowTemplateTest(unittest.TestCase):
    def test_builds_checkpoint_only_api_workflow(self):
        module = load_module()
        workflow = build(module)
        graph = workflow["prompt"]

        self.assertEqual(graph["1"]["class_type"], "CheckpointLoaderSimple")
        self.assertEqual(graph["3"]["inputs"]["clip"], ["1", 1])
        self.assertEqual(graph["5"]["inputs"]["width"], 1024)
        self.assertEqual(graph["5"]["inputs"]["height"], 1536)
        self.assertEqual(graph["9"]["inputs"]["model"], ["1", 0])
        self.assertEqual(graph["9"]["inputs"]["positive"], ["3", 0])
        self.assertEqual(graph["11"]["inputs"]["images"], ["10", 0])
        self.assertNotIn("LoraLoader", module.required_node_types(workflow))
        self.assertNotIn("ControlNetApplyAdvanced", module.required_node_types(workflow))

    def test_lora_updates_model_and_both_clip_inputs(self):
        module = load_module()
        workflow = build(
            module,
            lora_name="comic-style.safetensors",
            lora_strength_model=0.8,
            lora_strength_clip=0.6,
        )
        graph = workflow["prompt"]

        self.assertEqual(graph["2"]["class_type"], "LoraLoader")
        self.assertEqual(graph["2"]["inputs"]["model"], ["1", 0])
        self.assertEqual(graph["3"]["inputs"]["clip"], ["2", 1])
        self.assertEqual(graph["4"]["inputs"]["clip"], ["2", 1])
        self.assertEqual(graph["9"]["inputs"]["model"], ["2", 0])

    def test_controlnet_updates_positive_and_negative_conditioning(self):
        module = load_module()
        workflow = build(
            module,
            controlnet_name="control_v11p_sd15_lineart.pth",
            control_image="comic_pipeline/control/panel01.png",
            control_strength=0.75,
            control_start=0.1,
            control_end=0.9,
        )
        graph = workflow["prompt"]

        self.assertEqual(graph["6"]["class_type"], "LoadImage")
        self.assertEqual(graph["7"]["class_type"], "ControlNetLoader")
        self.assertEqual(graph["8"]["inputs"]["positive"], ["3", 0])
        self.assertEqual(graph["8"]["inputs"]["negative"], ["4", 0])
        self.assertEqual(graph["9"]["inputs"]["positive"], ["8", 0])
        self.assertEqual(graph["9"]["inputs"]["negative"], ["8", 1])

    def test_combined_template_is_json_serializable_and_prompts_are_editable(self):
        module = load_module()
        workflow = build(
            module,
            lora_name="comic-style.safetensors",
            controlnet_name="control_v11p_sd15_lineart.pth",
            control_image="comic_pipeline/control/panel01.png",
        )

        self.assertTrue(module.set_workflow_prompts(workflow, "new positive", "new negative"))
        self.assertEqual(workflow["prompt"]["3"]["inputs"]["text"], "new positive")
        self.assertEqual(workflow["prompt"]["4"]["inputs"]["text"], "new negative")
        self.assertIn("LoraLoader", module.required_node_types(workflow))
        self.assertIn("ControlNetApplyAdvanced", module.required_node_types(workflow))
        self.assertIsInstance(json.dumps(workflow), str)

    def test_env_config_maps_to_local_template_options(self):
        module = load_module()
        options = module.local_workflow_options({
            "COMIC_PIPELINE_COMFY_CHECKPOINT": "model.safetensors",
            "COMIC_PIPELINE_COMFY_LORA_NAME": "style.safetensors",
            "COMIC_PIPELINE_COMFY_LORA_STRENGTH_MODEL": "0.8",
            "COMIC_PIPELINE_COMFY_CONTROLNET_NAME": "lineart.pth",
            "COMIC_PIPELINE_COMFY_STEPS": "24",
            "COMIC_PIPELINE_COMFY_CFG": "6.5",
            "COMIC_PIPELINE_COMFY_SAMPLER": "euler",
            "COMIC_PIPELINE_COMFY_SCHEDULER": "normal",
        })
        self.assertEqual(options["checkpoint"], "model.safetensors")
        self.assertEqual(options["lora_strength_model"], 0.8)
        self.assertEqual(options["steps"], 24)
        self.assertEqual(options["cfg"], 6.5)
        self.assertEqual(options["sampler_name"], "euler")

    def test_rejects_incomplete_or_invalid_configuration(self):
        module = load_module()

        with self.assertRaisesRegex(ValueError, "checkpoint"):
            build(module, checkpoint="")
        with self.assertRaisesRegex(ValueError, "WIDTHxHEIGHT"):
            build(module, image_size="portrait")
        with self.assertRaisesRegex(ValueError, "divisible by 8"):
            build(module, image_size="1025x1536")
        with self.assertRaisesRegex(ValueError, "configured together"):
            build(module, controlnet_name="control.pth")
        with self.assertRaisesRegex(ValueError, "start < end"):
            build(
                module,
                controlnet_name="control.pth",
                control_image="control.png",
                control_start=0.8,
                control_end=0.2,
            )


if __name__ == "__main__":
    unittest.main()
