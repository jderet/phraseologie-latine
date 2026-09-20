from django.test import SimpleTestCase

from translations.segmentation import Sentence, from_lines, segment, to_lines


def texts(sentences):
    return [sentence.text for sentence in sentences]


class SegmentTests(SimpleTestCase):
    def test_sentences_end_with_a_final_mark(self):
        result = segment("Il pleut. Viendras-tu ? Oui ! Enfin… Nous verrons.", "fr")
        self.assertEqual(
            texts(result), ["Il pleut.", "Viendras-tu ?", "Oui !", "Enfin…", "Nous verrons."]
        )

    def test_lower_case_after_a_period_does_not_end_a_sentence(self):
        result = segment("Voir la note p. 12 et le chap. premier.", "fr")
        self.assertEqual(texts(result), ["Voir la note p. 12 et le chap. premier."])

    def test_abbreviations_and_initials(self):
        result = segment("M. Dupont et J. Martin arrivent. Ils sont en retard.", "fr")
        self.assertEqual(texts(result), ["M. Dupont et J. Martin arrivent.", "Ils sont en retard."])
        result = segment("Dr. Watson came in. Mr. Holmes did not.", "en")
        self.assertEqual(texts(result), ["Dr. Watson came in.", "Mr. Holmes did not."])

    def test_closing_quotes_stay_with_their_sentence(self):
        result = segment("Il a dit : « Bonjour ! » Puis il est parti.", "fr")
        self.assertEqual(texts(result), ["Il a dit : « Bonjour ! »", "Puis il est parti."])
        result = segment('He said "Stop." Then he left.', "en")
        self.assertEqual(texts(result), ['He said "Stop."', "Then he left."])

    def test_opening_marks_of_the_next_sentence(self):
        result = segment("¡Hola! ¿Qué tal? Bien.", "es")
        self.assertEqual(texts(result), ["¡Hola!", "¿Qué tal?", "Bien."])

    def test_german_ordinals(self):
        result = segment("Er kam am 3. Oktober an. Wir warteten.", "de")
        self.assertEqual(texts(result), ["Er kam am 3. Oktober an.", "Wir warteten."])

    def test_line_breaks_start_paragraphs(self):
        result = segment("Premier paragraphe. Suite.\n\nSecond paragraphe.\nTroisième.", "fr")
        self.assertEqual(
            result,
            [
                Sentence("Premier paragraphe.", starts_paragraph=True),
                Sentence("Suite."),
                Sentence("Second paragraphe.", starts_paragraph=True),
                Sentence("Troisième.", starts_paragraph=True),
            ],
        )

    def test_wikipedia_note_calls_are_removed(self):
        result = segment(
            "Paris est une ville[1]. Elle compte[réf. nécessaire] deux fleuves[a].", "fr"
        )
        self.assertEqual(texts(result), ["Paris est une ville.", "Elle compte deux fleuves."])

    def test_missing_spaces_after_the_marks(self):
        result = segment("Il vient.Elle part.Ils restent.", "fr")
        self.assertEqual(texts(result), ["Il vient.", "Elle part.", "Ils restent."])

    def test_a_mark_without_space_before_a_digit_or_a_lower_case_keeps_one_sentence(self):
        for text in ("Il mesure 2.5 mètres.", "Voir p.76 plus loin.", "Il cite J.Dupont ici."):
            self.assertEqual(texts(segment(text, "fr")), [text])

    def test_invisible_separators_are_read_as_spaces(self):
        result = segment("Il pleut.\u200bNous restons.\ufeff Demain.", "fr")
        self.assertEqual(texts(result), ["Il pleut.", "Nous restons.", "Demain."])

    def test_a_long_pasted_paragraph(self):
        """The passage that was reported as staying in one piece."""
        text = (
            "Parmi toutes les créatures d’Allah, les Chinois ont la main la plus habile à "
            "dessiner ; pour l’exécution de toutes sortes de travaux, il n’y a pas de peuple qui "
            "puisse faire mieux qu’eux. Un Chinois peut confectionner des choses que personne "
            "autre ne serait capable de faire. [Quand il a terminé un objet d’art], il l’apporte "
            "au gouverneur et réclame une récompense (p. 76). Un jour, un Chinois peignit un épi "
            "de blé sur un[Pg 85] moineau. «Tout homme d’expérience sait, dit-il, qu’un moineau "
            "ne peut pas se poser. Il a donc commis une faute.» La critique fut trouvée justifiée."
        )
        self.assertEqual(len(segment(text, "fr")), 7)

    def test_spaces_are_normalized(self):
        self.assertEqual(texts(segment("  Il   pleut.\t ", "fr")), ["Il pleut."])


class EditableFormTests(SimpleTestCase):
    def test_round_trip(self):
        sentences = [
            Sentence("Il pleut.", starts_paragraph=True),
            Sentence("Nous restons."),
            Sentence("Demain.", starts_paragraph=True),
        ]
        lines = to_lines(sentences)
        self.assertEqual(lines, "Il pleut.\nNous restons.\n\nDemain.")
        self.assertEqual(from_lines(lines), sentences)

    def test_checked_lines_are_kept_as_they_are(self):
        result = from_lines("Voir M.\nDupont.\n\n\n\nFin.\n")
        self.assertEqual(
            result,
            [
                Sentence("Voir M.", starts_paragraph=True),
                Sentence("Dupont."),
                Sentence("Fin.", starts_paragraph=True),
            ],
        )
