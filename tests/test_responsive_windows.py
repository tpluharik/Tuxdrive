from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]


class ResponsiveWindowTests(unittest.TestCase):
    def test_client_windows_do_not_force_maximization(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")

        self.assertIn("self.set_resizable(True)", source)
        self.assertNotIn("self.maximize()", source)
        self.assertIn("workarea.width * 0.92", source)
        self.assertIn("workarea.height * 0.92", source)

    def test_wide_job_controls_do_not_set_the_window_minimum_width(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/app.py").read_text(encoding="utf-8")

        self.assertIn(
            "actions_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)",
            source,
        )
        self.assertGreaterEqual(source.count("set_propagate_natural_width(False)"), 3)
        self.assertIn(
            "scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)",
            source,
        )

    def test_server_window_starts_resizable_without_forced_maximization(self) -> None:
        source = (REPOSITORY / "src/tuxindrive/server_gui.py").read_text(encoding="utf-8")

        self.assertIn("self.set_resizable(True)", source)
        self.assertNotIn("self.maximize()", source)


if __name__ == "__main__":
    unittest.main()
