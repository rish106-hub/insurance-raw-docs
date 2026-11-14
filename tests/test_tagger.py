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


class ProductNames(unittest.TestCase):
    insurer = 'HDFC Life Insurance Company Limited'

    def test_junk_names_rejected(self):
        for junk in ['<<Policyholder’s Name>>', '<<Master Policyholder’s Name>>', 'Sub: Your Policy no. 10023580', 'health', 'brochures',
                     'Policy Wording', 'CUSTOMER INFORMATION SHEET / KNOW YOUR POLICY', 'IRDA Reg. No. 115 CIN: L67200MH2000PLC12940',
                     'PART A: Covering Letter with Policy Schedule', 'Your Policy Details: Your Branch Representative Details:',
                     'HDFC Life Insurance', 'Welcome to Axis Max Life Insurance', 'In this Policy, unless the context requires otherwise',
                     'The list of covered critical illness surgical procedures and medical events is', 'A PLAN TO', 'Unique Identification Number',
                     'Toll free \u2013 1800-200-5577 e-mail : service.helpdesk@example.test', 'Why should you buy this plan?', 'and Policy Term',
                     'CHL Product Wealth Edge Plan copy']:
            self.assertTrue(tagger.bad_name(junk, self.insurer), junk)

    def test_real_names_kept(self):
        for good in ['HDFC Life Sanchay Plus', 'Domestic Staff Insurance Add-On', 'Star Group Health Insurance', 'Arogya Sanjeevani Policy',
                     'Assignment Form', 'my Optima Secure', 'Accident Care Gold Insurance']:
            self.assertFalse(tagger.bad_name(good, 'Star Health and Allied Insurance Company Limited'), good)

    def test_first_good_name_skips_junk_and_strips_uin(self):
        self.assertEqual(tagger.first_good_name([('<<Policyholder’s Name>>', 'link_page'), ('Health Protector 110N039V02 T&C', 'pdf_text')], self.insurer),
                         ('Health Protector T&C', 'pdf_text'))
        self.assertEqual(tagger.first_good_name([('health', 'a'), ('', 'b')], self.insurer), ('', ''))

    def test_url_names_cleaned(self):
        self.assertEqual(tagger.name_from_url('https://x/smart-lifelong-plan-136l032v03.pdf'), 'smart lifelong plan')
        self.assertEqual(tagger.name_from_url('https://x/PolicyWordings_Pre-PostHospitalizationMultiplierAdd-onCover.pdf'), 'Pre Post Hospitalization Multiplier Add on Cover')

    def test_file_like_titles_and_link_noise_cleaned(self):
        cases = {'POS_Easy_Bima_Sales_Literature_Final': 'POS Easy Bima', '23687_Pension4Life_Web_Bro_2024': 'Pension4Life',
                 '11 Accident Shield RSAPAIP05002V020405 Modified View View View View': 'Accident Shield',
                 'Protection Series Policy Document_': 'Protection Series'}
        for raw, want in cases.items():
            self.assertEqual(tagger.first_good_name([(raw, 'pdf_title')], 'Synthetic Insurance')[0], want, raw)

    def test_fill_names_prefers_same_uin_sibling_then_url(self):
        rows = [
            {'insurer_legal_name': self.insurer, 'uin': '101N097V08', 'product_name': 'HDFC Life Click 2 Invest', 'name_source': 'link_page', 'category': 'life_ulip', 'doc_type': 'brochure', 'tag_status': 'complete'},
            {'insurer_legal_name': self.insurer, 'uin': '101N097V08', 'product_name': '', 'name_source': '', 'category': 'life_ulip', 'doc_type': 'wording', 'tag_status': 'missing:product_name'},
            {'insurer_legal_name': self.insurer, 'uin': '', 'product_name': '', 'name_source': '', 'category': 'life_other', 'doc_type': 'other', 'tag_status': 'missing:uin|product_name'},
            {'insurer_legal_name': self.insurer, 'uin': '', 'product_name': '', 'name_source': '', 'category': 'life_other', 'doc_type': 'other', 'tag_status': 'missing:uin|product_name'},
        ]
        tagger.fill_names(rows, ['', 'ignored-url', 'hdfc-life-sampoorn-nivesh.pdf', 'brochures.pdf'])
        self.assertEqual((rows[1]['product_name'], rows[1]['name_source'], rows[1]['tag_status']), ('HDFC Life Click 2 Invest', 'sibling_uin', 'complete'))
        self.assertEqual((rows[2]['product_name'], rows[2]['name_source']), ('hdfc-life-sampoorn-nivesh.pdf', 'url'))
        self.assertEqual(rows[3]['product_name'], '', 'a junk URL name stays blank')


if __name__ == '__main__':
    unittest.main()
