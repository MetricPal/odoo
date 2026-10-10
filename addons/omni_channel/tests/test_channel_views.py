"""Database-free checks for the native channel overview view contract."""
from pathlib import Path
import unittest

from lxml import etree


class TestChannelViews(unittest.TestCase):
    def test_native_overview_team_panel_and_optional_columns(self):
        root = etree.parse(str(Path(__file__).resolve().parents[1] / 'views/omni_views.xml'))
        action = root.xpath('//record[@id="action_channels"]')[0]
        self.assertEqual(action.find("field[@name='view_mode']").text, 'kanban,list,form')
        self.assertEqual(action.find("field[@name='search_view_id']").get('ref'), 'channel_search')
        self.assertEqual(action.find("field[@name='limit']").text, '80')
        panel = root.xpath('//record[@id="channel_search"]//searchpanel')[0]
        self.assertEqual(panel.get('view_types'), 'kanban,list')
        self.assertEqual(panel.find('field').get('name'), 'purpose_id')
        self.assertEqual(panel.find('field').get('enable_counters'), '1')
        kanban = root.xpath('//record[@id="channel_kanban"]//kanban')[0]
        self.assertEqual(kanban.get('records_draggable'), 'false')
        self.assertFalse(kanban.get('class'))
        columns = root.xpath('//record[@id="channel_list"]//list/field')
        for column in columns:
            if column.get('name') not in {'name', 'purpose_id', 'channel_type_id', 'readiness'}:
                self.assertEqual(column.get('optional'), 'hide')


if __name__ == '__main__':
    unittest.main()
