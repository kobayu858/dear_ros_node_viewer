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

import os
import sys
import pytest
import networkx as nx
import yaml

# Add src to path so we can import the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dear_ros_node_viewer.caret_extend_agnocast import (
  _mark_agnocast_edges,
  _mark_agnocast_node_types,
  extend_agnocast,
)
from dear_ros_node_viewer.agnocast_extend_utils import (
  mark_bridge_nodes,
  synthesize_bridge_direct_edges,
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


def write_yaml(path: str, data: dict):
  with open(path, 'w', encoding='UTF-8') as f:
    yaml.dump(data, f)


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
# 1-3. Node type classification via YAML
# ===================================================================

class TestMarkAgnocastNodeTypes:
  """Tests for _mark_agnocast_node_types (reads architecture YAML)"""

  def test_node_type_classification(self, tmp_path):
    """
    /node_a belongs to agnocast_only_* executor -> agnocast_node (③)
    /node_b is in agnocast_* executor -> rclcpp_with_agnocast (②)
    /node_c has no agnocast executor -> rclcpp_only (①)
    """
    graph = make_graph_with_topics([
      ('/node_a', '/node_b', '/topic_agnocast'),
      ('/node_c', '/node_b', '/normal_topic'),
    ])

    arch = {
      'executors': [
        {
          'executor_type': 'agnocast_only_single_threaded',
          'callback_group_names': ['/node_a/cbg_0'],
        },
        {
          'executor_type': 'agnocast_single_threaded',
          'callback_group_names': ['/node_b/cbg_0'],
        },
      ],
      'nodes': [
        {
          'node_name': '/node_a',
          'callback_groups': [
            {'callback_group_name': '/node_a/cbg_0'}
          ],
        },
        {
          'node_name': '/node_b',
          'callback_groups': [
            {'callback_group_name': '/node_b/cbg_0'}
          ],
        },
        {
          'node_name': '/node_c',
          'callback_groups': [],
        },
      ],
    }
    yaml_file = str(tmp_path / 'architecture.yaml')
    write_yaml(yaml_file, arch)

    _mark_agnocast_node_types(graph, yaml_file)

    assert graph.nodes['"/node_a"']['agnocast_node_type'] == 'agnocast_node'
    assert graph.nodes['"/node_b"']['agnocast_node_type'] == 'rclcpp_with_agnocast'
    assert graph.nodes['"/node_c"']['agnocast_node_type'] == 'rclcpp_only'

  def test_empty_yaml(self, tmp_path):
    """Empty YAML should classify all nodes as rclcpp_only"""
    graph = make_graph_with_topics([
      ('/node_a', '/node_b', '/topic_agnocast'),
    ])

    yaml_file = str(tmp_path / 'architecture.yaml')
    write_yaml(yaml_file, {'nodes': [], 'executors': []})

    _mark_agnocast_node_types(graph, yaml_file)

    # No agnocast executors → all nodes are rclcpp_only
    assert graph.nodes['"/node_a"']['agnocast_node_type'] == 'rclcpp_only'
    assert graph.nodes['"/node_b"']['agnocast_node_type'] == 'rclcpp_only'


# ===================================================================
# 1-4. Graceful degradation (no node type classification)
# ===================================================================

class TestGracefulDegradation:
  """Tests that everything works without calling _mark_agnocast_node_types"""

  def test_extend_without_node_type(self):
    graph = make_graph_with_topics([
      ('/node_a', '/node_b', '/topic_agnocast'),
      ('/node_c', '/node_d', '/normal'),
    ])
    _mark_agnocast_edges(graph)
    mark_bridge_nodes(graph)
    synthesize_bridge_direct_edges(graph)

    # Edges should have is_agnocast
    for e in graph.edges:
      assert 'is_agnocast' in graph.edges[e]

    # Nodes should NOT have agnocast_node_type (set only by _mark_agnocast_node_types)
    for n in graph.nodes:
      assert 'agnocast_node_type' not in graph.nodes[n]


# ===================================================================
# Integration: extend_agnocast full function
# ===================================================================

class TestExtendAgnocastIntegration:
  """Integration tests for the full extend_agnocast function"""

  def _make_minimal_yaml(self, tmp_path, extra_nodes=None, executors=None):
    arch = {
      'nodes': extra_nodes or [],
      'executors': executors or [],
    }
    yaml_file = str(tmp_path / 'architecture.yaml')
    write_yaml(yaml_file, arch)
    return yaml_file

  def test_full_pipeline_basic(self, tmp_path):
    """Basic pipeline: agnocast edges marked, node types default to rclcpp_only when no executor YAML"""
    yaml_file = self._make_minimal_yaml(tmp_path)

    graph = make_graph_with_topics([
      ('/tracker', '/planner', '/tracks_agnocast'),
      ('/sensor', '/tracker', '/raw_data'),
    ])

    result = extend_agnocast(yaml_file, graph)

    # Verify edge attributes
    for e in result.edges:
      label = result.edges[e]['label']
      if label == '/tracks_agnocast':
        assert result.edges[e]['is_agnocast'] is True
      else:
        assert result.edges[e]['is_agnocast'] is False

    # No executor info in YAML → all nodes are rclcpp_only
    assert result.nodes['"/tracker"']['agnocast_node_type'] == 'rclcpp_only'
    assert result.nodes['"/planner"']['agnocast_node_type'] == 'rclcpp_only'
    assert result.nodes['"/sensor"']['agnocast_node_type'] == 'rclcpp_only'

  def test_full_pipeline_with_agnocast_only_executor(self, tmp_path):
    """Pipeline with agnocast_only executor sets agnocast_node_type correctly"""
    yaml_file = self._make_minimal_yaml(
      tmp_path,
      extra_nodes=[
        {
          'node_name': '/tracker',
          'callback_groups': [{'callback_group_name': '/tracker/cbg_0'}],
        },
        {
          'node_name': '/planner',
          'callback_groups': [{'callback_group_name': '/planner/cbg_0'}],
        },
        {
          'node_name': '/sensor',
          'callback_groups': [],
        },
      ],
      executors=[
        {
          'executor_type': 'agnocast_only_single_threaded',
          'callback_group_names': ['/tracker/cbg_0'],
        },
        {
          'executor_type': 'agnocast_single_threaded',
          'callback_group_names': ['/planner/cbg_0'],
        },
      ],
    )

    graph = make_graph_with_topics([
      ('/tracker', '/planner', '/tracks_agnocast'),
      ('/sensor', '/tracker', '/raw_data'),
    ])

    result = extend_agnocast(yaml_file, graph)

    assert result.nodes['"/tracker"']['agnocast_node_type'] == 'agnocast_node'
    assert result.nodes['"/planner"']['agnocast_node_type'] == 'rclcpp_with_agnocast'
    assert result.nodes['"/sensor"']['agnocast_node_type'] == 'rclcpp_only'

  def test_full_pipeline_with_bridge(self, tmp_path):
    """Test bridge node handling in full pipeline"""
    yaml_file = self._make_minimal_yaml(tmp_path)

    graph = nx.MultiDiGraph()
    graph.add_edge('"/tracker"', '"agnocast_bridge_node_999"',
            label='/tracks_agnocast')
    graph.add_edge('"agnocast_bridge_node_999"', '"/planner"',
            label='/tracks')

    result = extend_agnocast(yaml_file, graph)

    # Bridge node identified
    assert result.nodes['"agnocast_bridge_node_999"']['is_bridge_node'] is True

    # Direct edge synthesized
    bridged = [e for e in result.edges if result.edges[e].get('is_bridged', False)]
    assert len(bridged) == 1
    assert bridged[0][0] == '"/tracker"'
    assert bridged[0][1] == '"/planner"'
