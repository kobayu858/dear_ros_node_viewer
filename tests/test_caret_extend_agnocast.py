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
"""Tests for caret_extend_agnocast module"""

import json
import os
import sys
import tempfile
import pytest
import networkx as nx

# Add src to path so we can import the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dear_ros_node_viewer.caret_extend_agnocast import (
  _mark_agnocast_edges,
  _mark_agnocast_nodes,
  _mark_bridge_nodes,
  _synthesize_bridge_direct_edges,
  load_agnocast_info,
  _mark_agnocast_node_types,
  extend_agnocast,
)


# --- Helpers to build test graphs ---

def make_graph_with_topics(edges: list[tuple[str, str, str]]) -> nx.MultiDiGraph:
  """
  Build a MultiDiGraph from (src, dst, topic_label) tuples.
  Node names are quoted to match the real caret2networkx convention.
  """
  graph = nx.MultiDiGraph()
  for src, dst, label in edges:
    q_src = f'"{src}"'
    q_dst = f'"{dst}"'
    graph.add_edge(q_src, q_dst, label=label)
  return graph


def write_json(path: str, data: dict):
  with open(path, 'w', encoding='UTF-8') as f:
    json.dump(data, f)


# ===================================================================
# 1-1. Edge detection by _agnocast suffix
# ===================================================================

class TestMarkAgnocastEdges:
  """Tests for _mark_agnocast_edges"""

  def test_agnocast_suffix_detected(self):
    graph = make_graph_with_topics([
      ('/node_a', '/node_b', '/topic_agnocast'),
      ('/node_a', '/node_c', '/normal_topic'),
    ])
    _mark_agnocast_edges(graph)

    edges = list(graph.edges)
    edge_data = {graph.edges[e]['label']: graph.edges[e]['is_agnocast'] for e in edges}
    assert edge_data['/topic_agnocast'] is True
    assert edge_data['/normal_topic'] is False

  def test_suffix_must_be_exact(self):
    """'_agnocast_extra' should NOT match"""
    graph = make_graph_with_topics([
      ('/node_a', '/node_b', '/topic_agnocast_extra'),
    ])
    _mark_agnocast_edges(graph)
    edge = list(graph.edges)[0]
    assert graph.edges[edge]['is_agnocast'] is False

  def test_empty_graph(self):
    graph = nx.MultiDiGraph()
    _mark_agnocast_edges(graph)  # should not raise

  def test_quoted_label(self):
    """Labels with quotes should still be detected"""
    graph = nx.MultiDiGraph()
    graph.add_edge('"A"', '"B"', label='"/topic_agnocast"')
    _mark_agnocast_edges(graph)
    edge = list(graph.edges)[0]
    assert graph.edges[edge]['is_agnocast'] is True


# ===================================================================
# 1-2. Node has_agnocast derivation
# ===================================================================

class TestMarkAgnocastNodes:
  """Tests for _mark_agnocast_nodes"""

  def test_nodes_with_agnocast_edges(self):
    graph = make_graph_with_topics([
      ('/node_a', '/node_b', '/topic_agnocast'),
      ('/node_c', '/node_d', '/normal_topic'),
    ])
    _mark_agnocast_edges(graph)
    _mark_agnocast_nodes(graph)

    assert graph.nodes['"node_a"' if '"node_a"' in graph.nodes else '"/node_a"']['has_agnocast'] is True
    assert graph.nodes['"/node_b"']['has_agnocast'] is True
    assert graph.nodes['"/node_c"']['has_agnocast'] is False
    assert graph.nodes['"/node_d"']['has_agnocast'] is False

  def test_node_with_mixed_edges(self):
    """A node with both agnocast and normal edges should be has_agnocast=True"""
    graph = make_graph_with_topics([
      ('/node_a', '/node_b', '/topic_agnocast'),
      ('/node_a', '/node_c', '/normal_topic'),
    ])
    _mark_agnocast_edges(graph)
    _mark_agnocast_nodes(graph)

    assert graph.nodes['"/node_a"']['has_agnocast'] is True
    assert graph.nodes['"/node_c"']['has_agnocast'] is False


# ===================================================================
# 1-3. Bridge node detection
# ===================================================================

class TestBridgeDetection:
  """Tests for _mark_bridge_nodes and _synthesize_bridge_direct_edges"""

  def _make_bridge_graph(self):
    """Create a graph with a bridge node"""
    graph = nx.MultiDiGraph()
    # /fast_tracker -> bridge -> /planner
    graph.add_edge('"/fast_tracker"', '"agnocast_bridge_node_12345"',
            label='/tracks_agnocast')
    graph.add_edge('"agnocast_bridge_node_12345"', '"/planner"',
            label='/tracks')
    # Normal edge
    graph.add_edge('"/sensor"', '"/planner"', label='/data')
    return graph

  def test_bridge_node_identified(self):
    graph = self._make_bridge_graph()
    _mark_bridge_nodes(graph)

    assert graph.nodes['"agnocast_bridge_node_12345"']['is_bridge_node'] is True
    assert graph.nodes['"/fast_tracker"']['is_bridge_node'] is False
    assert graph.nodes['"/planner"']['is_bridge_node'] is False
    assert graph.nodes['"/sensor"']['is_bridge_node'] is False

  def test_bridge_edges_marked(self):
    graph = self._make_bridge_graph()
    _mark_bridge_nodes(graph)

    for edge in graph.edges:
      label = graph.edges[edge]['label']
      if 'bridge' in edge[0] or 'bridge' in edge[1]:
        assert graph.edges[edge]['is_bridge_edge'] is True
      else:
        assert graph.edges[edge]['is_bridge_edge'] is False

  def test_direct_edge_synthesized(self):
    graph = self._make_bridge_graph()
    _mark_bridge_nodes(graph)

    edge_count_before = graph.number_of_edges()
    _synthesize_bridge_direct_edges(graph)
    edge_count_after = graph.number_of_edges()

    # One new direct edge should be added
    assert edge_count_after == edge_count_before + 1

    # Check the synthesized edge
    synthesized = [e for e in graph.edges
            if graph.edges[e].get('is_bridged', False)]
    assert len(synthesized) == 1
    e = synthesized[0]
    assert e[0] == '"/fast_tracker"'
    assert e[1] == '"/planner"'
    assert graph.edges[e]['is_agnocast'] is True
    assert graph.edges[e]['is_bridged'] is True
    assert graph.edges[e]['is_bridge_edge'] is False

  def test_no_bridge_nodes(self):
    """Graph without bridge nodes should not get synthesized edges"""
    graph = make_graph_with_topics([
      ('/node_a', '/node_b', '/topic_agnocast'),
    ])
    _mark_bridge_nodes(graph)
    edge_count_before = graph.number_of_edges()
    _synthesize_bridge_direct_edges(graph)
    assert graph.number_of_edges() == edge_count_before

  def test_bridge_node_with_leading_slash(self):
    """Bridge node with / prefix (as in real YAML via quote_name)"""
    graph = nx.MultiDiGraph()
    graph.add_edge('"/sensor"', '"/agnocast_bridge_node_12345"',
            label='/camera_info')
    graph.add_edge('"/agnocast_bridge_node_12345"', '"/viewer"',
            label='/bridge/camera_info')
    _mark_bridge_nodes(graph)
    assert graph.nodes['"/agnocast_bridge_node_12345"']['is_bridge_node'] is True
    assert graph.nodes['"/sensor"']['is_bridge_node'] is False

  def test_bridge_node_with_namespace(self):
    """Bridge node under a namespace like /ns/agnocast_bridge_node_999"""
    graph = nx.MultiDiGraph()
    graph.add_edge('"/a"', '"/ns/agnocast_bridge_node_999"', label='/topic')
    graph.add_edge('"/ns/agnocast_bridge_node_999"', '"/b"', label='/out')
    _mark_bridge_nodes(graph)
    assert graph.nodes['"/ns/agnocast_bridge_node_999"']['is_bridge_node'] is True


# ===================================================================
# 1-4. JSON loading + node type classification
# ===================================================================

class TestAgnocastInfoLoading:
  """Tests for load_agnocast_info and _mark_agnocast_node_types"""

  def test_valid_json(self, tmp_path):
    json_file = str(tmp_path / 'agnocast_info.json')
    write_json(json_file, {
      'version': 1,
      'agnocast_nodes': ['/ns/node_a']
    })
    info = load_agnocast_info(json_file)
    assert info is not None
    assert info['agnocast_nodes'] == ['/ns/node_a']

  def test_unsupported_version(self, tmp_path):
    json_file = str(tmp_path / 'agnocast_info.json')
    write_json(json_file, {
      'version': 2,
      'agnocast_nodes': ['/ns/node_a']
    })
    info = load_agnocast_info(json_file)
    assert info is None

  def test_missing_file(self):
    info = load_agnocast_info('/nonexistent/path.json')
    assert info is None

  def test_none_file(self):
    info = load_agnocast_info(None)
    assert info is None

  def test_invalid_json(self, tmp_path):
    json_file = str(tmp_path / 'bad.json')
    with open(json_file, 'w') as f:
      f.write('not json{{{')
    info = load_agnocast_info(json_file)
    assert info is None

  def test_missing_agnocast_nodes_field(self, tmp_path):
    json_file = str(tmp_path / 'agnocast_info.json')
    write_json(json_file, {'version': 1})
    info = load_agnocast_info(json_file)
    assert info is None

  def test_node_type_classification(self, tmp_path):
    # /node_a publishes agnocast topic -> has_agnocast = True
    # /node_b subscribes agnocast topic -> has_agnocast = True
    # /node_c has no agnocast topic -> has_agnocast = False
    graph = make_graph_with_topics([
      ('/node_a', '/node_b', '/topic_agnocast'),
      ('/node_c', '/node_b', '/normal_topic'),
    ])
    _mark_agnocast_edges(graph)
    _mark_agnocast_nodes(graph)

    # /node_a is listed as agnocast_node -> type ③
    # /node_b is not listed but has_agnocast -> type ②
    # /node_c has no agnocast -> type ①
    agnocast_info = {
      'version': 1,
      'agnocast_nodes': ['/node_a']
    }
    _mark_agnocast_node_types(graph, agnocast_info)

    assert graph.nodes['"/node_a"']['agnocast_node_type'] == 'agnocast_node'
    assert graph.nodes['"/node_b"']['agnocast_node_type'] == 'rclcpp_with_agnocast'
    assert graph.nodes['"/node_c"']['agnocast_node_type'] == 'rclcpp_only'


# ===================================================================
# 1-5. Graceful degradation (no JSON)
# ===================================================================

class TestGracefulDegradation:
  """Tests that everything works without JSON file"""

  def test_extend_without_json(self):
    graph = make_graph_with_topics([
      ('/node_a', '/node_b', '/topic_agnocast'),
      ('/node_c', '/node_d', '/normal'),
    ])
    _mark_agnocast_edges(graph)
    _mark_agnocast_nodes(graph)
    _mark_bridge_nodes(graph)
    _synthesize_bridge_direct_edges(graph)

    # Edges should have is_agnocast
    for e in graph.edges:
      assert 'is_agnocast' in graph.edges[e]

    # Nodes should have has_agnocast but NOT agnocast_node_type
    for n in graph.nodes:
      assert 'has_agnocast' in graph.nodes[n]
      assert 'agnocast_node_type' not in graph.nodes[n]


# ===================================================================
# Integration: extend_agnocast full function
# ===================================================================

class TestExtendAgnocastIntegration:
  """Integration tests for the full extend_agnocast function"""

  def test_full_pipeline_without_json(self, tmp_path):
    """Test the full pipeline with YAML-only (no JSON)"""

    # Create a minimal architecture.yaml (not actually read by extend_agnocast
    # since we pass a pre-built graph, but filename is required)
    yaml_file = str(tmp_path / 'architecture.yaml')
    with open(yaml_file, 'w') as f:
      f.write('nodes: []\n')

    graph = make_graph_with_topics([
      ('/tracker', '/planner', '/tracks_agnocast'),
      ('/sensor', '/tracker', '/raw_data'),
    ])

    result = extend_agnocast(yaml_file, graph, agnocast_file=None)

    # Verify edge attributes
    for e in result.edges:
      label = result.edges[e]['label']
      if label == '/tracks_agnocast':
        assert result.edges[e]['is_agnocast'] is True
      else:
        assert result.edges[e]['is_agnocast'] is False

    # Verify node attributes
    assert result.nodes['"/tracker"']['has_agnocast'] is True
    assert result.nodes['"/planner"']['has_agnocast'] is True
    assert result.nodes['"/sensor"']['has_agnocast'] is False

    # No node types without JSON
    for n in result.nodes:
      assert 'agnocast_node_type' not in result.nodes[n]

  def test_full_pipeline_with_json(self, tmp_path):
    """Test the full pipeline with JSON supplementary file"""

    yaml_file = str(tmp_path / 'architecture.yaml')
    with open(yaml_file, 'w') as f:
      f.write('nodes: []\n')

    json_file = str(tmp_path / 'agnocast_info.json')
    write_json(json_file, {
      'version': 1,
      'agnocast_nodes': ['/tracker']
    })

    graph = make_graph_with_topics([
      ('/tracker', '/planner', '/tracks_agnocast'),
      ('/sensor', '/tracker', '/raw_data'),
    ])

    result = extend_agnocast(yaml_file, graph, agnocast_file=json_file)

    assert result.nodes['"/tracker"']['agnocast_node_type'] == 'agnocast_node'
    assert result.nodes['"/planner"']['agnocast_node_type'] == 'rclcpp_with_agnocast'
    assert result.nodes['"/sensor"']['agnocast_node_type'] == 'rclcpp_only'

  def test_full_pipeline_with_bridge(self, tmp_path):
    """Test bridge node handling in full pipeline"""

    yaml_file = str(tmp_path / 'architecture.yaml')
    with open(yaml_file, 'w') as f:
      f.write('nodes: []\n')

    graph = nx.MultiDiGraph()
    graph.add_edge('"/tracker"', '"agnocast_bridge_node_999"',
            label='/tracks_agnocast')
    graph.add_edge('"agnocast_bridge_node_999"', '"/planner"',
            label='/tracks')

    result = extend_agnocast(yaml_file, graph, agnocast_file=None)

    # Bridge node identified
    assert result.nodes['"agnocast_bridge_node_999"']['is_bridge_node'] is True

    # Direct edge synthesized
    bridged = [e for e in result.edges if result.edges[e].get('is_bridged', False)]
    assert len(bridged) == 1
    assert bridged[0][0] == '"/tracker"'
    assert bridged[0][1] == '"/planner"'
