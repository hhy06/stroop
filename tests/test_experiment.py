import unittest

from config import COLOR_KEYS, CONDITIONS, REPEATS_PER_CELL
from experiment import generate_sequence, latin_square_order, validate_sequence
from languages import LANGUAGE_KEYS, color_of_word, word_for


class TestSequence(unittest.TestCase):
    def test_full_balance_and_constraints_over_many_seeds(self):
        for seed in range(40):
            with self.subTest(seed=seed):
                seq = generate_sequence(seed, rotation=seed % len(LANGUAGE_KEYS))
                self.assertEqual(validate_sequence(seq), [])
                self.assertEqual(len(seq["test"]), len(LANGUAGE_KEYS) * len(CONDITIONS) * len(COLOR_KEYS) * REPEATS_PER_CELL)
                self.assertEqual(len(seq["practice"]), 8)

    def test_cells_are_exactly_balanced(self):
        from collections import Counter
        seq = generate_sequence(123)
        counts = Counter((t["language"], t["condition"], t["ink_color"]) for t in seq["test"])
        self.assertEqual(len(counts), len(LANGUAGE_KEYS) * len(CONDITIONS) * len(COLOR_KEYS))
        self.assertTrue(all(v == REPEATS_PER_CELL for v in counts.values()))

    def test_incongruent_word_never_matches_ink(self):
        seq = generate_sequence(5)
        for t in seq["test"]:
            if t["condition"] == "incongruent":
                self.assertNotEqual(color_of_word(t["language"], t["word"]), t["ink_color"])
            if t["condition"] == "congruent":
                self.assertEqual(word_for(t["language"], t["ink_color"]), t["word"])

    def test_reproducible_with_seed(self):
        self.assertEqual(generate_sequence(7, rotation=2), generate_sequence(7, rotation=2))
        self.assertNotEqual(generate_sequence(7), generate_sequence(8))

    def test_latin_square_rotation(self):
        langs = ["zh", "en", "es", "de"]
        self.assertEqual(latin_square_order(langs, 0), langs)
        self.assertEqual(latin_square_order(langs, 1), ["en", "es", "de", "zh"])
        self.assertEqual(latin_square_order(langs, 4), langs)

    def test_custom_languages_and_repeats(self):
        seq = generate_sequence(3, languages=["zh", "en"], repeats_per_cell=5)
        self.assertEqual(len(seq["test"]), 2 * 3 * 4 * 5)
        self.assertEqual(validate_sequence(seq, repeats_per_cell=5), [])
        self.assertEqual(seq["block_order"], ["zh", "en"])

    def test_reject_unknown_language_and_bad_repeats(self):
        with self.assertRaises(ValueError):
            generate_sequence(1, languages=["klingon"])
        with self.assertRaises(ValueError):
            generate_sequence(1, repeats_per_cell=0)


if __name__ == "__main__":
    unittest.main()
