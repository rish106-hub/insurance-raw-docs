"""Regression cases for tag-catalog.py. Run: python3 tests/test_tagger.py (from any directory)."""
import importlib.util, os, unittest

spec = importlib.util.spec_from_file_location('tagger', os.path.join(os.path.dirname(__file__), '..', 'tag-catalog.py'))
tagger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tagger)


def row(name, uin, insurer='Synthetic General Insurance Limited'):
    return {'insurer_legal_name': insurer, 'product_name': name, 'uin': uin}


class SiblingIndex(unittest.TestCase):
    def test_generic_names_never_spread_a_uin(self):
        # Pass 4 bug: "health" / "Policy Wording" / "brochures" spread one UIN over unrelated products.
        idx = tagger.sibling_index([row('health', 'SYNHLIP26055V102526'), row('Policy Wording', 'SYNHLIP21344V022021'),
                                    row('brochures', '101N139V09')])
        self.assertEqual(dict(idx['Synthetic General Insurance Limited']), {})

    def test_name_with_two_uins_is_not_inherited(self):
        idx = tagger.sibling_index([row('Optima Secure', 'SYNHLIP26058V082526'), row('Optima Secure', 'SYNHLIP22021V042122')])
        self.assertNotIn('optima secure', idx['Synthetic General Insurance Limited'])

    def test_specific_single_uin_name_is_inherited(self):
        idx = tagger.sibling_index([row('Optima Secure Policy Wording', 'SYNHLIP26058V082526')])
        self.assertEqual(idx['Synthetic General Insurance Limited']['optima secure policy wording'], 'SYNHLIP26058V082526')

    def test_scoped_per_insurer(self):
        idx = tagger.sibling_index([row('Arogya Plan', 'AAAHLIP21043V012122', 'Insurer A'), row('Arogya Plan', 'BBBHLIP27036V022627', 'Insurer B')])
        self.assertEqual(idx['Insurer A']['arogya plan'], 'AAAHLIP21043V012122')
        self.assertEqual(idx['Insurer B']['arogya plan'], 'BBBHLIP27036V022627')


class LinkWins(unittest.TestCase):
    modern = 'BAJPAIP08004V010708'
    irda_ref = 'IRDA/NL-HLT/BAGI/P-P/V.I/278/13-14'

    def test_old_irda_reference_does_not_beat_modern_link_uin(self):
        # Pass 4 bug: an IRDA-era reference printed in the PDF replaced the product's modern UIN.
        self.assertTrue(tagger.link_wins(self.modern, 'NOTHINGHERE', self.irda_ref))

    def test_modern_pdf_uin_beats_link_uin_absent_from_pdf(self):
        # Link pages often show another card's UIN next to a PDF; the document wins.
        self.assertFalse(tagger.link_wins('101B041V01', 'UIN:101N139V09', '101N139V09'))

    def test_link_uin_kept_when_pdf_contains_it(self):
        self.assertTrue(tagger.link_wins('101N139V09', 'XX101N139V09XX', '101N146V11'))

    def test_link_uin_kept_when_pdf_has_no_clear_uin(self):
        self.assertTrue(tagger.link_wins(self.modern, '', ''))

    def test_empty_candidate_never_wins(self):
        self.assertFalse(tagger.link_wins('', 'ANY', ''))


if __name__ == '__main__':
    unittest.main()
