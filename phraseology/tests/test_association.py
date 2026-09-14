from django.test import SimpleTestCase

from phraseology.association import log_likelihood


class LogLikelihoodTests(SimpleTestCase):
    def test_an_attracted_pair(self):
        # 10 pairs out of 1000, each word in 20 pairs: 0.4 expected by chance.
        self.assertAlmostEqual(log_likelihood(10, 20, 20, 1000), 56.76, places=2)

    def test_a_pair_rarer_than_chance_is_negative(self):
        self.assertLess(log_likelihood(1, 500, 500, 1000), 0)

    def test_independence_scores_zero(self):
        self.assertAlmostEqual(log_likelihood(25, 50, 500, 1000), 0.0)

    def test_inconsistent_frequencies(self):
        for values in ((0, 1, 1, 10), (5, 4, 10, 100), (5, 10, 10, 9)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                log_likelihood(*values)
