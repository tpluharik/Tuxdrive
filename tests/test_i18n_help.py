import unittest

from tuxdrive.help_content import topics
from tuxdrive.i18n import LANGUAGES, get_language, set_language, tr


class LocalizationAndHelpTests(unittest.TestCase):
    def tearDown(self):
        set_language("en")

    def test_four_languages_have_matching_complete_help_topics(self):
        expected = [item.key for item in topics("en")]
        self.assertEqual(len(expected), 18)
        for language in LANGUAGES:
            localized = topics(language.code)
            self.assertEqual([item.key for item in localized], expected)
            self.assertTrue(all(len(item.title) > 3 and len(item.body) > 80 for item in localized))

    def test_translations_switch_and_unknown_language_falls_back(self):
        values = set()
        for code in ("en", "de", "fr", "es"):
            set_language(code)
            values.add(tr("settings"))
        self.assertEqual(len(values), 4)
        self.assertEqual(set_language("unsupported"), "en")
        self.assertEqual(get_language(), "en")
        self.assertEqual(tr("missing-key"), "missing-key")


if __name__ == "__main__":
    unittest.main()
