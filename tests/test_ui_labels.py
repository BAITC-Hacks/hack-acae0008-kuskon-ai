"""Small display-only checks; score calculation remains in scoring.py."""
import unittest

from ui import catalog_rank_label, score_gain_label


class UILabelTests(unittest.TestCase):
    def test_rank_labels(self):
        self.assertEqual(catalog_rank_label(2, 5, 'ru'), '#2 из 5 по рейтингу')
        self.assertEqual(catalog_rank_label(1, 1, 'en'), '#1 of 1 by score')
        self.assertEqual(catalog_rank_label(1, 3, 'kk'), 'Рейтинг бойынша #1 / 3')

    def test_gain_only_for_increase(self):
        self.assertEqual(score_gain_label(45, 70, 'ru'), 'Прирост +25.')
        for lang in ('ru', 'kk', 'en'):
            with self.subTest(lang=lang):
                self.assertIn('+25', score_gain_label(45, 70, lang))
                self.assertEqual(score_gain_label(70, 70, lang), '')
                self.assertEqual(score_gain_label(70, 45, lang), '')


if __name__ == '__main__':
    unittest.main()
