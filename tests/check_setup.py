"""Offline tests for CosmoACE initial-setup helper and wizard macros."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_PY = REPO_ROOT / "files" / "ace-setup.py"
MACROS = REPO_ROOT / "files" / "ace_macros.cfg"

# Ensure check_macros helpers are importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_macros  # noqa: E402


def load_setup_module():
    spec = importlib.util.spec_from_file_location("ace_setup", SETUP_PY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class SetupHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ace-setup-test-"))
        self.addon = self.tmp / "addon"
        self.cfg = self.tmp / "config"
        self.addon.mkdir()
        self.cfg.mkdir()
        (self.cfg / "printer.cfg").write_text(
            "[include klipper-readonly/*.cfg]\n\n"
            "[filament_switch_sensor runout]\n"
            "switch_pin: ^PC0\n"
            "pause_on_runout: False\n\n"
            "[filament_switch_sensor toolhead_runout_sensor]\n"
            "switch_pin: !hotend:PB2\n"
            "pause_on_runout: False\n\n"
            "[gcode_button toolhead_cutter_detection]\n"
            "pin: !hotend:PC5\n\n"
            "#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            "#*# [input_shaper]\n"
            "#*# shaper_type_x = mzv\n",
            encoding="utf-8",
        )
        (self.cfg / "ace-addon.cfg").write_text(
            '[gcode_macro _ACE_CONFIG]\nvariable_sensor_name: "runout"\n'
            'variable_toolhead_sensor_name: "toolhead_runout_sensor"\ngcode:\n',
            encoding="utf-8",
        )
        self.setup = load_setup_module()
        self.setup.configure_paths(addon_dir=self.addon, config_dir=self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_marker_persistence(self):
        self.assertFalse(self.setup.is_complete())
        self.setup.mark_complete()
        self.assertTrue(self.setup.is_complete())
        self.assertTrue((self.addon / "setup_complete").is_file())
        self.setup.clear_complete()
        self.assertFalse(self.setup.is_complete())

    def test_hub_config_idempotent(self):
        self.setup.write_hub_config()
        hw = (self.cfg / "ace-hardware.cfg").read_text(encoding="utf-8")
        self.assertIn("[filament_switch_sensor HUB]", hw)
        self.assertIn("Managed by CosmoACE setup", hw)
        printer = (self.cfg / "printer.cfg").read_text(encoding="utf-8")
        self.assertIn("[include ace-hardware.cfg]", printer)
        # Active duplicate in printer.cfg should be commented.
        self.assertIn("moved to ace-hardware.cfg", printer)
        macros = (self.cfg / "ace-addon.cfg").read_text(encoding="utf-8")
        self.assertIn('variable_sensor_name: "HUB"', macros)

        # Second apply should remain stable.
        self.setup.write_hub_config()
        printer2 = (self.cfg / "printer.cfg").read_text(encoding="utf-8")
        self.assertEqual(printer2.count("[include ace-hardware.cfg]"), 1)
        self.assertTrue((self.addon / "setup_hub_mode").read_text().strip() == "hub")

    def test_managed_file_owns_toolhead_hardware(self):
        self.setup.write_hub_config()
        hw = (self.cfg / "ace-hardware.cfg").read_text(encoding="utf-8")
        for section in (
            "[filament_switch_sensor HUB]",
            "[filament_switch_sensor toolhead_runout_sensor]",
            "[gcode_button toolhead_front_cover_detection]",
            "[gcode_button toolhead_cutter_detection]",
        ):
            self.assertIn(section, hw)

        printer = (self.cfg / "printer.cfg").read_text(encoding="utf-8")
        for section in (
            "[filament_switch_sensor runout]",
            "[filament_switch_sensor toolhead_runout_sensor]",
            "[gcode_button toolhead_cutter_detection]",
        ):
            self.assertNotIn(f"\n{section}", "\n" + printer)
            self.assertIn(f"# {section}", printer)
        # SAVE_CONFIG must survive untouched.
        self.assertIn("#*# shaper_type_x = mzv", printer)

    def test_hubless_config_clears_sensor_name(self):
        self.setup.write_hubless_config()
        hw = (self.cfg / "ace-hardware.cfg").read_text(encoding="utf-8")
        self.assertIn("mode: hubless", hw)
        self.assertNotIn("[filament_switch_sensor HUB]", hw)
        # Toolhead hardware is hub-independent and stays in the managed file.
        self.assertIn("[filament_switch_sensor toolhead_runout_sensor]", hw)
        macros = (self.cfg / "ace-addon.cfg").read_text(encoding="utf-8")
        self.assertIn('variable_sensor_name: ""', macros)
        self.assertEqual((self.addon / "setup_hub_mode").read_text().strip(), "hubless")

    def test_backup_and_remove_managed(self):
        self.setup.write_hub_config()
        self.setup.mark_complete()
        self.setup.queue_resume("_ACE_SETUP_AFTER_HUB_RESTART")
        backups = list((self.addon / "setup-backups").glob("*"))
        self.assertTrue(backups)

        rc = self.setup.remove_managed_hardware(restore_sensor_name="HUB")
        self.assertEqual(rc, 0)
        self.assertFalse((self.cfg / "ace-hardware.cfg").exists())
        self.assertFalse(self.setup.is_complete())
        printer = (self.cfg / "printer.cfg").read_text(encoding="utf-8")
        self.assertNotIn("[include ace-hardware.cfg]", printer)
        macros = (self.cfg / "ace-addon.cfg").read_text(encoding="utf-8")
        self.assertIn('variable_sensor_name: "HUB"', macros)

    def test_remove_managed_keeps_canvas_toolhead(self):
        self.setup.write_hub_config()
        rc = self.setup.remove_managed_hardware(
            restore_sensor_name="HUB",
            keep_canvas_toolhead=True,
        )
        self.assertEqual(rc, 0)
        self.assertFalse((self.cfg / "ace-hardware.cfg").exists())
        canvas = (self.cfg / "canvas.cfg").read_text(encoding="utf-8")
        self.assertIn("[filament_switch_sensor toolhead_runout_sensor]", canvas)
        self.assertIn("[gcode_button toolhead_cutter_detection]", canvas)
        self.assertIn("[gcode_button toolhead_front_cover_detection]", canvas)
        self.assertNotIn("[filament_switch_sensor HUB]", canvas)
        self.assertNotIn("_ACE_SENSOR_EVENT", canvas)
        self.assertIn("pause_on_runout: True", canvas)
        printer = (self.cfg / "printer.cfg").read_text(encoding="utf-8")
        self.assertIn("[include canvas.cfg]", printer)
        self.assertNotIn("[include ace-hardware.cfg]", printer)

    def test_write_hub_disables_canvas_include(self):
        (self.cfg / "canvas.cfg").write_text(
            "[filament_switch_sensor toolhead_runout_sensor]\n"
            "switch_pin: !hotend:PB2\n",
            encoding="utf-8",
        )
        printer = (self.cfg / "printer.cfg").read_text(encoding="utf-8")
        (self.cfg / "printer.cfg").write_text(
            printer + "\n[include canvas.cfg]\n", encoding="utf-8"
        )
        self.setup.write_hub_config()
        printer2 = (self.cfg / "printer.cfg").read_text(encoding="utf-8")
        self.assertNotIn("[include canvas.cfg]", printer2)
        self.assertIn("[include ace-hardware.cfg]", printer2)
        self.assertTrue((self.cfg / "canvas.cfg").exists())

    def test_apply_hub_queues_resume(self):
        self.setup.apply_hub()
        self.assertTrue((self.addon / "setup_resume.gcode").is_file())
        self.assertIn(
            "_ACE_SETUP_AFTER_HUB_RESTART",
            (self.addon / "setup_resume.gcode").read_text(),
        )

    def test_macros_include_avoids_klipper_readonly(self):
        readonly = self.cfg / "klipper-readonly"
        readonly.mkdir()
        # CosmOS used a symlink; on Windows tests just plant a wipe-prone file.
        legacy = readonly / "ace-addon.cfg"
        legacy.write_text("legacy wipe-prone stub\n", encoding="utf-8")

        self.setup.ensure_macros_include()
        printer = (self.cfg / "printer.cfg").read_text(encoding="utf-8")
        self.assertIn("[include ace-addon.cfg]", printer)
        self.assertFalse(legacy.exists())

        # Idempotent.
        self.setup.ensure_macros_include()
        printer2 = (self.cfg / "printer.cfg").read_text(encoding="utf-8")
        self.assertEqual(printer2.count("[include ace-addon.cfg]"), 1)

        self.setup.remove_macros_include()
        printer3 = (self.cfg / "printer.cfg").read_text(encoding="utf-8")
        self.assertNotIn("[include ace-addon.cfg]", printer3)


class SetupMacroTests(unittest.TestCase):
    WIZARD_MACROS = [
        "ACE_INITIAL_SETUP",
        "ACE_SETUP_RETRY",
        "_ACE_SETUP_PROMPT_HUB",
        "_ACE_SETUP_CHOOSE_HUB",
        "_ACE_SETUP_CHOOSE_HUBLESS",
        "_ACE_SETUP_AFTER_HUB_RESTART",
        "_ACE_SETUP_PROMPT_CLEAR_HUB",
        "_ACE_SETUP_AFTER_HUBLESS_RESTART",
        "_ACE_SETUP_VALIDATE_HUB",
        "_ACE_SETUP_PROMPT_LANE",
        "_ACE_SETUP_PROMPT_LANE_FAIL",
        "_ACE_SETUP_TEST_LANE",
        "_ACE_SETUP_FINISH_HUB",
        "_ACE_SETUP_FINISH_HUBLESS",
        "_ACE_SETUP_STOP",
        "_ACE_SETUP_EXIT",
        "_ACE_SETUP_ASSERT_IDLE",
        "_ACE_SETUP_CLOSE_PROMPT",
    ]

    def test_wizard_macros_compile(self):
        failures = check_macros.compile_all(str(MACROS))
        self.assertEqual(failures, [])

    def test_wizard_macros_present(self):
        parser = check_macros.load(str(MACROS))
        for name in self.WIZARD_MACROS:
            self.assertTrue(
                parser.has_section(f"gcode_macro {name}"),
                f"missing [gcode_macro {name}]",
            )
        self.assertTrue(parser.has_section("gcode_macro _ACE_SETUP_STATE"))
        self.assertTrue(parser.has_section("delayed_gcode _ACE_SETUP_BOOT"))
        self.assertTrue(parser.has_section("gcode_shell_command ace_setup"))

    def _render(self, name, params=None, printing=False, paused=False, hub=0, active=0, hub_mode=-1, lane=1):
        parser = check_macros.load(str(MACROS))
        env = check_macros.klipper_env()
        template = env.from_string(parser.get(f"gcode_macro {name}", "gcode"))
        printer = check_macros.build_printer(True, hub, 0, True)
        printer["print_stats"] = {"state": "printing" if printing else "standby"}
        printer["pause_resume"] = {"is_paused": paused}
        printer["gcode_macro _ACE_SETUP_STATE"] = {
            "active": active,
            "hub_mode": hub_mode,
            "lane": lane,
            "last_error": "",
        }
        return template.render(
            params=params or {},
            rawparams="",
            printer=printer,
            action_raise_error=check_macros.raise_error,
            action_respond_info=lambda m: "",
            action_emergency_stop=lambda m="": "",
        )

    def test_assert_idle_blocks_printing(self):
        with self.assertRaises(RuntimeError):
            self._render("_ACE_SETUP_ASSERT_IDLE", printing=True)

    def test_assert_idle_blocks_paused(self):
        with self.assertRaises(RuntimeError):
            self._render("_ACE_SETUP_ASSERT_IDLE", paused=True)

    def test_prompt_hub_renders(self):
        out = self._render("_ACE_SETUP_PROMPT_HUB")
        self.assertIn("action:prompt_begin ACE Initial Setup", out)
        self.assertIn("_ACE_SETUP_CHOOSE_HUB", out)
        self.assertIn("_ACE_SETUP_CHOOSE_HUBLESS", out)
        self.assertIn("_ACE_SETUP_EXIT", out)

    def test_lane_prompt_renders(self):
        out = self._render("_ACE_SETUP_PROMPT_LANE", active=1, hub_mode=1, lane=2)
        self.assertIn("Lane 2", out)
        self.assertIn("_ACE_SETUP_TEST_LANE", out)

    def test_lane_fail_prompt_has_retry_stop_exit(self):
        out = self._render("_ACE_SETUP_PROMPT_LANE_FAIL", active=1, hub_mode=1, lane=3)
        self.assertIn("Retry", out)
        self.assertIn("_ACE_SETUP_STOP", out)
        self.assertIn("_ACE_SETUP_EXIT", out)

    def test_test_lane_refuses_triggered_hub(self):
        with self.assertRaises(RuntimeError):
            self._render(
                "_ACE_SETUP_TEST_LANE",
                active=1,
                hub_mode=1,
                lane=1,
                hub=1,
            )

    def test_test_lane_happy_path_commands(self):
        out = self._render(
            "_ACE_SETUP_TEST_LANE",
            active=1,
            hub_mode=1,
            lane=1,
            hub=0,
        )
        self.assertIn("_ACE_LOAD_TO_SENSOR", out)
        self.assertIn("SPEED=8", out)
        self.assertIn("_ACE_UNLOAD_TO_SENSOR", out)
        self.assertIn("_ACE_CLEAR_HUB", out)

    def test_initial_setup_resumes_fail_menu(self):
        out = self._render(
            "ACE_INITIAL_SETUP",
            active=1,
            hub_mode=1,
            lane=2,
        )
        self.assertIn("_ACE_SETUP_PROMPT_LANE_FAIL", out)

    def test_after_hub_restart_prompts_clear_when_triggered(self):
        out = self._render(
            "_ACE_SETUP_AFTER_HUB_RESTART",
            active=1,
            hub_mode=1,
            lane=1,
            hub=1,
        )
        self.assertIn("_ACE_SETUP_PROMPT_CLEAR_HUB", out)

    def test_exit_clears_complete(self):
        out = self._render("_ACE_SETUP_EXIT")
        self.assertIn('PARAMS="clear_complete"', out)


if __name__ == "__main__":
    # Also exercise the shared macro compile/render suite.
    if "--with-macros" in sys.argv:
        sys.argv.remove("--with-macros")
        rc = check_macros.main()
        if rc:
            raise SystemExit(rc)
    unittest.main()
