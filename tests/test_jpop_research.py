import unittest
from unittest.mock import Mock
from jpop_research import month_windows, matched_artist, extract_items, KOPISClient, create_review_table

class TestJpopResearch(unittest.TestCase):
    def test_month_windows(self):
        self.assertEqual(month_windows(2024, [12, 2, 2]), [("20240201", "20240229"), ("20241201", "20241231")])

    def test_matching(self):
        self.assertEqual(matched_artist("후지이 카제 내한 공연"), "Fujii Kaze")
        self.assertEqual(matched_artist("일반 국내 공연"), "")

    def test_ado_does_not_match_other_artists(self):
        self.assertEqual(matched_artist("아도(Ado) THE FIRST WORLD TOUR: Wish"), "Ado")
        self.assertEqual(matched_artist("빈첸 PADO vol.3"), "")
        self.assertEqual(matched_artist("ADOBT STAGE: 김오키"), "")
        self.assertEqual(matched_artist("SHADOW BAND"), "")
        self.assertEqual(matched_artist("Ado Live 2024"), "Ado")

    def test_xml(self):
        self.assertEqual(extract_items("<dbs><db><mt20id>PF1</mt20id></db></dbs>"), [{"mt20id": "PF1"}])

    def test_pagination(self):
        c = KOPISClient("TEST_KEY")
        c.get = Mock(side_effect=[[{"mt20id": f"PF{i}"} for i in range(100)], [{"mt20id": "PF1", "prfnm": "updated"}]])
        data, info = c.collect(2024, [2], max_pages=3)
        self.assertEqual(len(data), 100)
        self.assertEqual(info["requests_made"], 2)

    def test_review(self):
        df = create_review_table([{"mt20id":"PF1","prfnm":"Ado live"}])
        self.assertIn("일본 아티스트 여부(확인 필요)", df.columns)

if __name__ == "__main__":
    unittest.main()
