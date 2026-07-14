# Copyright 2023 iwatake2222
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Unit tests for agnocast_extend_utils.py
"""

import unittest
import networkx as nx

from dear_ros_node_viewer.agnocast_extend_utils import (
    base_topic,
    extract_node_basename,
    mark_bridge_nodes,
    synthesize_bridge_direct_edges,
)


class TestAgnocastExtendUtils(unittest.TestCase):

    # ===================================================================
    # 1. Name Parsing Tests
    # ===================================================================

    def test_base_topic(self):
        """Test suffix stripping for topics."""
        self.assertEqual(base_topic('"/sensing/lidar_agnocast"'), '/sensing/lidar')
        self.assertEqual(base_topic('/chatter_agnocast'), '/chatter')
        self.assertEqual(base_topic('/chatter'), '/chatter')
        self.assertEqual(base_topic('"/quoted_normal"'), '/quoted_normal')

    def test_extract_node_basename(self):
        """Test basename extraction from full paths and quotes."""
        self.assertEqual(extract_node_basename('/ns/node'), 'node')
        self.assertEqual(extract_node_basename('"/ns/node"'), 'node')
        self.assertEqual(extract_node_basename('/node'), 'node')
        self.assertEqual(extract_node_basename('node'), 'node')
        self.assertEqual(extract_node_basename('"/agnocast_bridge_node_123"'), 'agnocast_bridge_node_123')


    # ===================================================================
    # 2. Bridge Node & Edge Marking Tests
    # ===================================================================

    def _make_bridge_graph(self) -> nx.MultiDiGraph:
        """Create a basic graph with a bridge node."""
        g = nx.MultiDiGraph()
        g.add_edge('"/sensor"', '"/agnocast_bridge_node_123"', label='/data_agnocast')
        g.add_edge('"/agnocast_bridge_node_123"', '"/planner"', label='/data')
        g.add_edge('"/other_node"', '"/planner"', label='/other')
        return g

    def test_mark_bridge_nodes_identifies_correctly(self):
        g = self._make_bridge_graph()
        mark_bridge_nodes(g)

        self.assertTrue(g.nodes['"/agnocast_bridge_node_123"'].get('is_bridge_node'))
        self.assertFalse(g.nodes['"/sensor"'].get('is_bridge_node', False))
        self.assertFalse(g.nodes['"/planner"'].get('is_bridge_node', False))

    def test_mark_bridge_nodes_marks_connected_edges(self):
        g = self._make_bridge_graph()
        mark_bridge_nodes(g)

        for u, v, key, data in g.edges(keys=True, data=True):
            if 'bridge_node' in u or 'bridge_node' in v:
                self.assertTrue(data['is_bridge_edge'])
            else:
                self.assertFalse(data['is_bridge_edge'])

    def test_mark_bridge_nodes_with_namespace(self):
        """Bridge node under a namespace should still be detected."""
        g = nx.MultiDiGraph()
        g.add_edge('"/a"', '"/ns/agnocast_bridge_node_999"', label='/topic')
        mark_bridge_nodes(g)
        self.assertTrue(g.nodes['"/ns/agnocast_bridge_node_999"'].get('is_bridge_node'))


    # ===================================================================
    # 3. Direct Edge Synthesis Tests
    # ===================================================================

    def test_synthesize_bridge_direct_edges_creates_new_edge(self):
        g = self._make_bridge_graph()
        mark_bridge_nodes(g)
        
        edge_count_before = g.number_of_edges()
        # default: upgrade_existing_edges=False
        synthesize_bridge_direct_edges(g)
        
        self.assertEqual(g.number_of_edges(), edge_count_before + 1)

        # Verify the synthesized edge attributes
        synthesized_edges = [data for u, v, data in g.edges(data=True) if data.get('is_bridged')]
        self.assertEqual(len(synthesized_edges), 1)
        
        edge_data = synthesized_edges[0]
        self.assertTrue(edge_data['is_agnocast'])
        self.assertTrue(edge_data['is_bridged'])
        self.assertFalse(edge_data['is_bridge_edge'])
        self.assertEqual(edge_data['label_src'], '/data_agnocast')
        self.assertEqual(edge_data['label_dst'], '/data')

    def test_synthesize_bridge_direct_edges_upgrade_existing(self):
        """Test that an existing edge is upgraded rather than duplicated when upgrade=True."""
        g = self._make_bridge_graph()
        # Manually add the direct edge beforehand (simulating what runtime Phase 4 does)
        g.add_edge('"/sensor"', '"/planner"', label='/data', existing_attr='keep_me')
        mark_bridge_nodes(g)
        
        edge_count_before = g.number_of_edges()
        synthesize_bridge_direct_edges(g, upgrade_existing_edges=True)
        
        # No new edge should be added, the existing one should be upgraded
        self.assertEqual(g.number_of_edges(), edge_count_before)
        
        # Get the upgraded edge data
        edge_data = g.get_edge_data('"/sensor"', '"/planner"')
        found_upgraded = False
        for key, data in edge_data.items():
            if data.get('label') == '/data' and data.get('is_bridged'):
                found_upgraded = True
                self.assertEqual(data['existing_attr'], 'keep_me')
                self.assertEqual(data['label_src'], '/data_agnocast')
        
        self.assertTrue(found_upgraded, "Existing edge was not upgraded.")

    def test_synthesize_no_bridge_nodes(self):
        """Graph without bridge nodes should remain unchanged."""
        g = nx.MultiDiGraph()
        g.add_edge('"/node_a"', '"/node_b"', label='/normal')
        
        mark_bridge_nodes(g)
        edge_count_before = g.number_of_edges()
        synthesize_bridge_direct_edges(g)
        
        self.assertEqual(g.number_of_edges(), edge_count_before)


if __name__ == '__main__':
    unittest.main()

