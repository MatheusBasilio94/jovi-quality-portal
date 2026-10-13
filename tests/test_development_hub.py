import unittest
from urllib.parse import urlparse

from tools.development_hub import documents


class DevelopmentHubTests(unittest.TestCase):
    def test_catalog_and_links(self):
        rows = documents()
        self.assertEqual(len(rows), 86)
        self.assertEqual(sum(bool(row['url']) for row in rows), 82)
        self.assertEqual(len({(row['type'], row['number']) for row in rows}), 86)
        for row in rows:
            self.assertFalse(any('\u3400' <= character <= '\u9fff' for character in row['title']))
            if row['url']:
                self.assertIn(urlparse(row['url']).hostname, {'bpm.vivo.xyz', 'global-bpm.vivo.xyz', 'global.bpm.vivo.xyz'})
                self.assertIn(urlparse(row['url']).scheme, {'http', 'https'})

    def test_administrator_view_and_filters(self):
        from streamlit.testing.v1 import AppTest
        script = '''
import streamlit as st
from tools.development_hub import render
st.session_state['authenticated'] = True
st.session_state['auth_role'] = 'admin'
render()
'''
        app = AppTest.from_string(script).run(timeout=15)
        self.assertFalse(app.exception)
        catalog = next(item.value for item in app.dataframe if 'Document title' in item.value.columns)
        self.assertEqual(len(catalog), 83)
        app.selectbox(key='development_area').set_value('SMT').run()
        self.assertFalse(app.exception)
        catalog = next(item.value for item in app.dataframe if 'Document title' in item.value.columns)
        self.assertTrue(catalog['Area'].str.contains('SMT').all())
        app.text_input(key='development_search').set_value('SMT OQC').run()
        catalog = next(item.value for item in app.dataframe if 'Document title' in item.value.columns)
        self.assertEqual(len(catalog), 1)

    def test_viewer_cannot_render_document_catalog(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string('''
import streamlit as st
from tools.development_hub import render
st.session_state['authenticated'] = True
st.session_state['auth_role'] = 'viewer'
render()
''').run(timeout=15)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 0)
        self.assertTrue(app.error)


if __name__ == '__main__':
    unittest.main()
