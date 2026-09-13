from django.test import SimpleTestCase

from corpus.text import normalize, normalize_space, tokenize

SENTENCES = [
    "Quo usque tandem abutere, Catilina, patientia nostra?",
    "«quid multa?» inquit.",
    "Gallia est omnis divisa in partes tres (cf. Caes. Gall. 1, 1).",
    "Non tamen omnino Marci nostri ληκύθους fugimus.",
    "  Quamquam te, Marce fili, annum iam audientem Cratippum  ",
    "anno 45 — consilium cēpit…",
    "***",
]


class NormalizeTests(SimpleTestCase):
    def test_search_forms(self):
        cases = {
            "Vīvō": "uiuo",
            "Iūlius": "iulius",
            "jam": "iam",
            "Cæsar": "caesar",
            "cœlum": "coelum",
            "poëta": "poeta",
            "CONSILIVM": "consilium",
            "cōnsilium": "consilium",
            "ἀρετή": "αρετη",
        }
        for form, expected in cases.items():
            with self.subTest(form=form):
                self.assertEqual(normalize(form), expected)

    def test_is_idempotent(self):
        for form in ("Vīvō", "Cæsar", "Iuppiter", "ληκύθους"):
            with self.subTest(form=form):
                self.assertEqual(normalize(normalize(form)), normalize(form))

    def test_normalize_space(self):
        self.assertEqual(normalize_space("  consilium\n   capere "), "consilium capere")
        self.assertEqual(normalize_space("cōnsilium"), "cōnsilium")


class TokenizeTests(SimpleTestCase):
    def test_text_is_rebuilt_exactly(self):
        for sentence in SENTENCES:
            with self.subTest(sentence=sentence):
                tokens = tokenize(sentence)
                self.assertEqual(
                    "".join(t.before + t.form + t.after for t in tokens) or sentence, sentence
                )

    def test_words_and_following_punctuation(self):
        tokens = tokenize("Quo usque tandem abutere, Catilina, patientia nostra?")
        self.assertEqual(
            [t.form for t in tokens],
            ["Quo", "usque", "tandem", "abutere", "Catilina", "patientia", "nostra"],
        )
        self.assertEqual([t.after for t in tokens], [" ", " ", " ", ", ", ", ", " ", "?"])

    def test_opening_marks_belong_to_the_next_word(self):
        tokens = tokenize("«quid multa?» inquit.")
        self.assertEqual(
            [(t.before, t.form, t.after) for t in tokens],
            [
                ("«", "quid", " "),
                ("", "multa", "?» "),
                ("", "inquit", "."),
            ],
        )
        tokens = tokenize("partes tres (cf. Caes.)")
        self.assertEqual(tokens[2].before, "(")
        self.assertEqual(tokens[3].after, ".)")

    def test_marks_without_space_stay_with_the_previous_word(self):
        tokens = tokenize("dixit,sed")
        self.assertEqual([(t.form, t.after) for t in tokens], [("dixit", ","), ("sed", "")])

    def test_printed_forms_are_kept(self):
        self.assertEqual([t.form for t in tokenize("cōnsilium cēpit")], ["cōnsilium", "cēpit"])

    def test_numbers_are_words(self):
        self.assertEqual([t.form for t in tokenize("anno 45")], ["anno", "45"])

    def test_greek_words_are_marked_foreign(self):
        tokens = tokenize("Marci nostri ληκύθους fugimus")
        self.assertEqual([t.is_foreign for t in tokens], [False, False, True, False])

    def test_decomposed_marks_stay_inside_the_word(self):
        self.assertEqual([t.form for t in tokenize("cōnsilium cepit")], ["cōnsilium", "cepit"])

    def test_text_without_words(self):
        self.assertEqual(tokenize("***"), [])
