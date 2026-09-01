import unittest
from pathlib import Path


class SeoDocumentTests(unittest.TestCase):
    def test_public_document_has_complete_social_and_search_metadata(self):
        document = Path("public/index.html").read_text()

        expected = [
            "<title>SOXL Analysis Platform",
            'name="description"',
            'rel="canonical" href="https://soxlpro.xyz/"',
            'name="google-site-verification"',
            'property="og:title"',
            'property="og:description"',
            'property="og:url"',
            'property="og:image" content="https://soxlpro.xyz/social-preview"',
            'property="og:type"',
            'property="og:site_name"',
            'name="twitter:card" content="summary_large_image"',
            'name="twitter:title"',
            'name="twitter:description"',
            'name="twitter:image" content="https://soxlpro.xyz/social-preview"',
            'type="application/ld+json"',
            "<h1",
        ]
        for item in expected:
            with self.subTest(item=item):
                self.assertIn(item, document)

        self.assertNotIn("<title>Streamlit</title>", document)


if __name__ == "__main__":
    unittest.main()