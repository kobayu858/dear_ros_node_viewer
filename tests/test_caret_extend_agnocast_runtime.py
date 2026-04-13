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
Unit tests for caret_extend_agnocast_runtime.py

Tests are grouped:
  - Parser tests: verify CLI output parsing logic
  - Graph modification tests: verify attribute setting on NetworkX graphs
  - Integration tests: verify the full pipeline with mocked CLI
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

import networkx as nx

# Allow importing the module without the full package structure.
# We need to intercept the relative import (.logger_factory) by
# pre-populating sys.modules with a stub package.
sys.path.insert(0, os.path.dirname(__file__))

# Create a stub package so that relative imports resolve
_pkg_name = 'dear_ros_node_viewer'
if _pkg_name not in sys.modules:
  import types
  _pkg = types.ModuleType(_pkg_name)
  _pkg.__path__ = [os.path.dirname(__file__)]
  _pkg.__package__ = _pkg_name
  sys.modules[_pkg_name] = _pkg

# Stub the logger_factory sub-module
logger_mock = MagicMock()
logger_factory_module = MagicMock()
logger_factory_module.LoggerFactory.create.return_value = logger_mock
sys.modules[f'{_pkg_name}.logger_factory'] = logger_factory_module

# Stub caret2networkx (for quote_name, if ever needed)
caret2networkx_module = MagicMock()
caret2networkx_module.quote_name = lambda name: '"' + name + '"'
sys.modules[f'{_pkg_name}.caret2networkx'] = caret2networkx_module

# Now import the module under test as a sub-module of the stub package
import importlib.util
_spec = importlib.util.spec_from_file_location(
  f'{_pkg_name}.caret_extend_agnocast_runtime',
  os.path.join(os.path.dirname(__file__), 'caret_extend_agnocast_runtime.py'),
  submodule_search_locations=[]
)
runtime = importlib.util.module_from_spec(_spec)
runtime.__package__ = _pkg_name
sys.modules[_spec.name] = runtime
_spec.loader.exec_module(runtime)


# ===========================================================================
# Parser tests
# ===========================================================================

class TestParseNodeListAgnocast(unittest.TestCase):
  """Tests for _parse_node_list_agnocast."""

  def test_basic(self):
    output = (
      "/planner\n"
      "/lidar\n"
      "/detector (Agnocast enabled)\n"
      "/tracker (Agnocast enabled)\n"
    )
    agnocast_only, all_nodes = runtime._parse_node_list_agnocast(output)
    self.assertEqual(agnocast_only, {'/detector', '/tracker'})
    self.assertEqual(all_nodes, {'/planner', '/lidar', '/detector', '/tracker'})

  def test_empty_output(self):
    agnocast_only, all_nodes = runtime._parse_node_list_agnocast("")
    self.assertEqual(agnocast_only, set())
    self.assertEqual(all_nodes, set())

  def test_no_agnocast_nodes(self):
    output = "/planner\n/lidar\n"
    agnocast_only, all_nodes = runtime._parse_node_list_agnocast(output)
    self.assertEqual(agnocast_only, set())
    self.assertEqual(all_nodes, {'/planner', '/lidar'})

  def test_blank_lines_ignored(self):
    output = "\n/planner\n\n/detector (Agnocast enabled)\n\n"
    agnocast_only, all_nodes = runtime._parse_node_list_agnocast(output)
    self.assertEqual(agnocast_only, {'/detector'})
    self.assertEqual(all_nodes, {'/planner', '/detector'})


class TestParseNodeInfoAgnocast(unittest.TestCase):
  """Tests for _parse_node_info_agnocast."""

  def test_basic_pub_sub(self):
    output = (
      "  Publishers:\n"
      "    /points: sensor_msgs/msg/PointCloud2 (Agnocast enabled)\n"
      "    /image: sensor_msgs/msg/Image (Agnocast enabled)\n"
      "  Subscribers:\n"
      "    /control_cmd: autoware_msgs/msg/ControlCommand (Agnocast enabled)\n"
    )
    pubs, subs = runtime._parse_node_info_agnocast(output)
    self.assertEqual(pubs, {'/points', '/image'})
    self.assertEqual(subs, {'/control_cmd'})

  def test_empty_sections(self):
    output = (
      "  Publishers:\n"
      "  Subscribers:\n"
    )
    pubs, subs = runtime._parse_node_info_agnocast(output)
    self.assertEqual(pubs, set())
    self.assertEqual(subs, set())

  def test_mixed_sections_filters_non_agnocast(self):
    """ROS 2 topics (no Agnocast suffix) are filtered out, Agnocast topics are kept."""
    output = (
      "  Publishers:\n"
      "    /topic_a: msg/TypeA (Agnocast enabled)\n"
      "    /ros2_only: msg/TypeR\n"
      "  Subscribers:\n"
      "    /topic_b: msg/TypeB (Agnocast enabled, bridged)\n"
      "    /ros2_sub: msg/TypeS\n"
      "  Service Servers:\n"
      "    /srv_a: srv/TypeA\n"
    )
    pubs, subs = runtime._parse_node_info_agnocast(output)
    self.assertEqual(pubs, {'/topic_a'})
    self.assertEqual(subs, {'/topic_b'})

  def test_empty_output(self):
    pubs, subs = runtime._parse_node_info_agnocast("")
    self.assertEqual(pubs, set())
    self.assertEqual(subs, set())


class TestParseTopicListAgnocast(unittest.TestCase):
  """Tests for _parse_topic_list_agnocast."""

  def test_basic(self):
    output = (
      "/topic_a (Agnocast enabled)\n"
      "/topic_b (Agnocast enabled, bridged)\n"
      "/topic_c\n"
      "/topic_d (WARN: Agnocast and ROS2 endpoints exist but bridge is not active)\n"
    )
    topics = runtime._parse_topic_list_agnocast(output)
    # /topic_c has no (Agnocast marker; /topic_d WARN line doesn't contain '(Agnocast'
    self.assertIn('/topic_a', topics)
    self.assertIn('/topic_b', topics)
    self.assertNotIn('/topic_c', topics)
    self.assertNotIn('/topic_d', topics)  # WARN line starts with (WARN, not (Agnocast

  def test_empty(self):
    topics = runtime._parse_topic_list_agnocast("")
    self.assertEqual(topics, set())


class TestParseSingleTopicInfo(unittest.TestCase):
  """Tests for _parse_single_topic_info."""

  def test_basic(self):
    block = (
      "Type: sensor_msgs/msg/PointCloud2\n"
      "\n"
      "ROS 2 Publisher count: 1\n"
      "Agnocast Publisher count: 1\n"
      "\n"
      "Node name: lidar_driver\n"
      "Node namespace: /sensing\n"
      "Topic type: sensor_msgs/msg/PointCloud2\n"
      "Endpoint type: PUBLISHER (Agnocast enabled)\n"
      "\n"
      "ROS 2 Subscription count: 0\n"
      "Agnocast Subscription count: 1\n"
      "\n"
      "Node name: detector\n"
      "Node namespace: /perception\n"
      "Topic type: sensor_msgs/msg/PointCloud2\n"
      "Endpoint type: SUBSCRIPTION (Agnocast enabled)\n"
    )
    endpoints = runtime._parse_single_topic_info(block)
    self.assertEqual(len(endpoints.agnocast_pubs), 1)
    self.assertEqual(endpoints.agnocast_pubs[0].node_name, '/sensing/lidar_driver')
    self.assertFalse(endpoints.agnocast_pubs[0].is_bridge)
    self.assertEqual(len(endpoints.agnocast_subs), 1)
    self.assertEqual(endpoints.agnocast_subs[0].node_name, '/perception/detector')

  def test_bridge_node_detected(self):
    block = (
      "Type: sensor_msgs/msg/PointCloud2\n"
      "\n"
      "ROS 2 Publisher count: 0\n"
      "Agnocast Publisher count: 1\n"
      "\n"
      "Node name: agnocast_bridge_node_12345\n"
      "Node namespace: /\n"
      "Topic type: sensor_msgs/msg/PointCloud2\n"
      "Endpoint type: PUBLISHER (Agnocast enabled)\n"
      "\n"
      "ROS 2 Subscription count: 0\n"
      "Agnocast Subscription count: 0\n"
    )
    endpoints = runtime._parse_single_topic_info(block)
    self.assertEqual(len(endpoints.agnocast_pubs), 1)
    self.assertTrue(endpoints.agnocast_pubs[0].is_bridge)

  def test_ros2_endpoints_ignored(self):
    block = (
      "Type: std_msgs/msg/String\n"
      "\n"
      "ROS 2 Publisher count: 1\n"
      "\n"
      "Node name: ros_pub\n"
      "Node namespace: /\n"
      "Topic type: std_msgs/msg/String\n"
      "Endpoint type: PUBLISHER\n"
      "\n"
      "Agnocast Publisher count: 0\n"
      "ROS 2 Subscription count: 1\n"
      "\n"
      "Node name: ros_sub\n"
      "Node namespace: /\n"
      "Topic type: std_msgs/msg/String\n"
      "Endpoint type: SUBSCRIPTION\n"
      "\n"
      "Agnocast Subscription count: 0\n"
    )
    endpoints = runtime._parse_single_topic_info(block)
    self.assertEqual(len(endpoints.agnocast_pubs), 0)
    self.assertEqual(len(endpoints.agnocast_subs), 0)


class TestParseAllTopicInfoAgnocast(unittest.TestCase):
  """Tests for _parse_all_topic_info_agnocast."""

  def test_multiple_topics(self):
    output = (
      "--- /points ---\n"
      "Type: sensor_msgs/msg/PointCloud2\n"
      "\n"
      "ROS 2 Publisher count: 0\n"
      "Agnocast Publisher count: 1\n"
      "\n"
      "Node name: lidar\n"
      "Node namespace: /sensing\n"
      "Topic type: sensor_msgs/msg/PointCloud2\n"
      "Endpoint type: PUBLISHER (Agnocast enabled)\n"
      "\n"
      "ROS 2 Subscription count: 0\n"
      "Agnocast Subscription count: 0\n"
      "\n"
      "--- /image ---\n"
      "Type: sensor_msgs/msg/Image\n"
      "\n"
      "ROS 2 Publisher count: 0\n"
      "Agnocast Publisher count: 1\n"
      "\n"
      "Node name: camera\n"
      "Node namespace: /sensing\n"
      "Topic type: sensor_msgs/msg/Image\n"
      "Endpoint type: PUBLISHER (Agnocast enabled)\n"
      "\n"
      "ROS 2 Subscription count: 0\n"
      "Agnocast Subscription count: 0\n"
    )
    result = runtime._parse_all_topic_info_agnocast(output)
    self.assertIn('/points', result)
    self.assertIn('/image', result)
    self.assertEqual(len(result), 2)
    self.assertEqual(result['/points'].agnocast_pubs[0].node_name,
             '/sensing/lidar')
    self.assertEqual(result['/image'].agnocast_pubs[0].node_name,
             '/sensing/camera')

  def test_empty(self):
    result = runtime._parse_all_topic_info_agnocast("")
    self.assertEqual(result, {})


# ===========================================================================
# Graph modification tests
# ===========================================================================

def _make_simple_graph() -> nx.MultiDiGraph:
  """Create a simple test graph mimicking dot2networkx output.

  Graph:
    "/node_a" --(/topic_x)--> "/node_b" --(/topic_y)--> "/node_c"
  """
  g = nx.MultiDiGraph()
  g.add_node('"/node_a"')
  g.add_node('"/node_b"')
  g.add_node('"/node_c"')
  g.add_edge('"/node_a"', '"/node_b"', label='/topic_x')
  g.add_edge('"/node_b"', '"/node_c"', label='/topic_y')
  return g


class TestAddAgnocastNodes(unittest.TestCase):
  """Tests for _add_agnocast_nodes."""

  def test_add_new_node_with_edges(self):
    """③ node is added with edges to existing nodes."""
    g = _make_simple_graph()
    agnocast_only = {'/detector'}
    node_topics = {'/detector': ({'/topic_y'}, {'/topic_x'})}

    g = runtime._add_agnocast_nodes(g, agnocast_only, node_topics)

    self.assertIn('"/detector"', g.nodes)
    # /detector publishes /topic_y → should connect to /node_c
    found_pub_edge = False
    for src, dst, _ in g.edges:
      if src == '"/detector"' and dst == '"/node_c"':
        found_pub_edge = True
    self.assertTrue(found_pub_edge, "Missing pub edge: /detector → /node_c")

    # /detector subscribes /topic_x → should connect from /node_a
    found_sub_edge = False
    for src, dst, _ in g.edges:
      if src == '"/node_a"' and dst == '"/detector"':
        found_sub_edge = True
    self.assertTrue(found_sub_edge, "Missing sub edge: /node_a → /detector")

  def test_skip_existing_node(self):
    """② node already in graph should not be duplicated."""
    g = _make_simple_graph()
    agnocast_only = {'/node_b'}  # already in graph as "/node_b"
    node_topics = {}

    node_count_before = len(g.nodes)
    g = runtime._add_agnocast_nodes(g, agnocast_only, node_topics)
    self.assertEqual(len(g.nodes), node_count_before)

  def test_skip_bridge_node(self):
    """Bridge nodes are not added by _add_agnocast_nodes."""
    g = _make_simple_graph()
    agnocast_only = {'/agnocast_bridge_node_1234'}
    node_topics = {}

    g = runtime._add_agnocast_nodes(g, agnocast_only, node_topics)
    self.assertNotIn('"/agnocast_bridge_node_1234"', g.nodes)

  def test_no_edges_when_no_topics(self):
    """③ node with no topic info adds no edges."""
    g = _make_simple_graph()
    agnocast_only = {'/orphan'}
    node_topics = {}  # no info for /orphan

    edge_count_before = len(g.edges)
    g = runtime._add_agnocast_nodes(g, agnocast_only, node_topics)
    self.assertIn('"/orphan"', g.nodes)
    self.assertEqual(len(g.edges), edge_count_before)


class TestMarkAgnocastEdges(unittest.TestCase):
  """Tests for _mark_agnocast_edges."""

  def test_marks_agnocast_edge(self):
    g = _make_simple_graph()
    topic_endpoints = {
      '/topic_x': runtime.TopicEndpoints(
        agnocast_pubs=[runtime.EndpointInfo('/node_a', False)],
        agnocast_subs=[runtime.EndpointInfo('/node_b', False)],
      )
    }
    g = runtime._mark_agnocast_edges(g, topic_endpoints)

    for src, dst, key in g.edges:
      label = g.edges[src, dst, key].get('label', '').strip('"')
      if label == '/topic_x':
        self.assertTrue(g.edges[src, dst, key]['is_agnocast'])
      elif label == '/topic_y':
        self.assertFalse(g.edges[src, dst, key]['is_agnocast'])

  def test_none_endpoints_sets_false(self):
    g = _make_simple_graph()
    g = runtime._mark_agnocast_edges(g, None)

    for edge in g.edges:
      self.assertFalse(g.edges[edge]['is_agnocast'])

  def test_skips_already_marked(self):
    """Edges from _add_agnocast_nodes (already is_agnocast=True) are preserved."""
    g = _make_simple_graph()
    # Simulate an edge added by _add_agnocast_nodes
    g.add_edge('"/new_node"', '"/node_c"', label='/topic_y', is_agnocast=True)

    topic_endpoints = {}  # no info
    g = runtime._mark_agnocast_edges(g, topic_endpoints)

    # The pre-marked edge should remain True
    for src, dst, key in g.edges:
      if src == '"/new_node"':
        self.assertTrue(g.edges[src, dst, key]['is_agnocast'])


class TestMarkAgnocastNodes(unittest.TestCase):
  """Tests for _mark_agnocast_nodes."""

  def test_basic_classification(self):
    g = _make_simple_graph()
    # Mark one edge as agnocast
    for src, dst, key in g.edges:
      label = g.edges[src, dst, key].get('label', '')
      g.edges[src, dst, key]['is_agnocast'] = (label == '/topic_x')

    agnocast_only = {'/node_a'}  # ③ node
    g = runtime._mark_agnocast_nodes(g, agnocast_only)

    self.assertEqual(g.nodes['"/node_a"']['agnocast_node_type'], 'agnocast_node')
    self.assertEqual(g.nodes['"/node_b"']['agnocast_node_type'], 'rclcpp_with_agnocast')
    self.assertEqual(g.nodes['"/node_c"']['agnocast_node_type'], 'rclcpp_only')

  def test_has_agnocast_derived_from_edges(self):
    g = _make_simple_graph()
    for edge in g.edges:
      g.edges[edge]['is_agnocast'] = False
    # Make /topic_x agnocast
    for src, dst, key in g.edges:
      if g.edges[src, dst, key].get('label', '') == '/topic_x':
        g.edges[src, dst, key]['is_agnocast'] = True

    g = runtime._mark_agnocast_nodes(g, None)
    self.assertTrue(g.nodes['"/node_a"']['has_agnocast'])
    self.assertTrue(g.nodes['"/node_b"']['has_agnocast'])
    self.assertFalse(g.nodes['"/node_c"']['has_agnocast'])

  def test_no_node_type_when_agnocast_only_is_none(self):
    g = _make_simple_graph()
    for edge in g.edges:
      g.edges[edge]['is_agnocast'] = False

    g = runtime._mark_agnocast_nodes(g, None)
    self.assertNotIn('agnocast_node_type', g.nodes['"/node_a"'])


class TestProcessBridgeNodes(unittest.TestCase):
  """Tests for _process_bridge_nodes."""

  def test_bridge_detection_and_synthesis(self):
    g = nx.MultiDiGraph()
    g.add_node('"/sensing/lidar"')
    g.add_node('"/agnocast_bridge_node_999"')
    g.add_node('"/planning/planner"')
    g.add_edge('"/sensing/lidar"', '"/agnocast_bridge_node_999"',
           label='/points_agnocast')
    g.add_edge('"/agnocast_bridge_node_999"', '"/planning/planner"',
           label='/points')

    g = runtime._process_bridge_nodes(g)

    # Bridge node marked
    self.assertTrue(g.nodes['"/agnocast_bridge_node_999"']['is_bridge_node'])
    self.assertFalse(g.nodes['"/sensing/lidar"']['is_bridge_node'])

    # Bridge edges marked
    bridge_edge_count = 0
    synthesized_edge = None
    for edge in g.edges:
      if g.edges[edge].get('is_bridge_edge', False):
        bridge_edge_count += 1
      if g.edges[edge].get('is_bridged', False):
        synthesized_edge = edge

    self.assertEqual(bridge_edge_count, 2)
    self.assertIsNotNone(synthesized_edge)

    # Check synthesized edge attributes
    data = g.edges[synthesized_edge]
    self.assertTrue(data['is_agnocast'])
    self.assertTrue(data['is_bridged'])
    self.assertFalse(data['is_bridge_edge'])
    self.assertEqual(data['label_src'], '/points_agnocast')
    self.assertEqual(data['label_dst'], '/points')

  def test_no_bridge_nodes(self):
    g = _make_simple_graph()
    g = runtime._process_bridge_nodes(g)

    for node_name in g.nodes:
      self.assertFalse(g.nodes[node_name].get('is_bridge_node', False))
    for edge in g.edges:
      self.assertFalse(g.edges[edge].get('is_bridge_edge', False))

  def test_bridge_with_namespace(self):
    """Bridge node with namespace is still detected."""
    g = nx.MultiDiGraph()
    g.add_node('"/ns/agnocast_bridge_node_42"')
    g.add_node('"/node_a"')
    g.add_edge('"/node_a"', '"/ns/agnocast_bridge_node_42"', label='/t')

    g = runtime._process_bridge_nodes(g)
    self.assertTrue(g.nodes['"/ns/agnocast_bridge_node_42"']['is_bridge_node'])


# ===========================================================================
# Integration tests (full pipeline with mocked CLI)
# ===========================================================================

class TestExtendAgnocastRuntimeIntegration(unittest.TestCase):
  """Integration tests for extend_agnocast_runtime with mocked subprocess."""

  # Patch target: the subprocess module inside the runtime module object
  _PATCH_TARGET = f'{runtime.__name__}.subprocess.run'

  def _mock_run(self, cmd_outputs: dict):
    """Create a side_effect function for subprocess.run mock.

    Parameters
    ----------
    cmd_outputs : dict
        ``{command_key: stdout_string}`` where command_key is a substring
        that uniquely identifies the command.
    """
    def side_effect(cmd, **kwargs):
      cmd_str = ' '.join(cmd)
      for key, stdout in cmd_outputs.items():
        if key in cmd_str:
          result = MagicMock()
          result.returncode = 0
          result.stdout = stdout
          result.stderr = ''
          return result
      # Command not found in outputs → return failure
      result = MagicMock()
      result.returncode = 1
      result.stdout = ''
      result.stderr = 'not found'
      return result
    return side_effect

  def test_full_pipeline(self):
    """Full pipeline: ③ node added, edges connected, attributes set."""
    node_list_output = (
      "/node_a\n"
      "/node_b\n"
      "/detector (Agnocast enabled)\n"
    )
    node_info_output = (
      "  Publishers:\n"
      "    /topic_y: msg/Type (Agnocast enabled)\n"
      "  Subscribers:\n"
      "    /topic_x: msg/Type (Agnocast enabled)\n"
    )
    topic_list_output = (
      "/topic_x (Agnocast enabled)\n"
      "/topic_y (Agnocast enabled)\n"
    )
    topic_info_topic_x = (
      "Type: msg/Type\n"
      "\n"
      "ROS 2 Publisher count: 0\n"
      "Agnocast Publisher count: 1\n"
      "\n"
      "Node name: node_a\n"
      "Node namespace: /\n"
      "Topic type: msg/Type\n"
      "Endpoint type: PUBLISHER (Agnocast enabled)\n"
      "\n"
      "ROS 2 Subscription count: 0\n"
      "Agnocast Subscription count: 1\n"
      "\n"
      "Node name: node_b\n"
      "Node namespace: /\n"
      "Topic type: msg/Type\n"
      "Endpoint type: SUBSCRIPTION (Agnocast enabled)\n"
    )
    topic_info_topic_y = (
      "Type: msg/Type\n"
      "\n"
      "ROS 2 Publisher count: 0\n"
      "Agnocast Publisher count: 0\n"
      "ROS 2 Subscription count: 0\n"
      "Agnocast Subscription count: 0\n"
    )

    def side_effect(cmd, **kwargs):
      cmd_str = ' '.join(cmd)
      result = MagicMock()
      result.stderr = ''
      if 'node list_agnocast' in cmd_str:
        result.returncode = 0
        result.stdout = node_list_output
      elif 'node info_agnocast' in cmd_str:
        result.returncode = 0
        result.stdout = node_info_output
      elif 'topic list_agnocast' in cmd_str:
        result.returncode = 0
        result.stdout = topic_list_output
      elif 'topic info_agnocast' in cmd_str and '/topic_x' in cmd_str:
        result.returncode = 0
        result.stdout = topic_info_topic_x
      elif 'topic info_agnocast' in cmd_str and '/topic_y' in cmd_str:
        result.returncode = 0
        result.stdout = topic_info_topic_y
      else:
        result.returncode = 1
        result.stdout = ''
        result.stderr = 'not found'
      return result

    with patch.object(runtime.subprocess, 'run', side_effect=side_effect):
      g = _make_simple_graph()
      g = runtime.extend_agnocast_runtime(g)

    # ③ node /detector should be added
    self.assertIn('"/detector"', g.nodes)

    # Node types
    self.assertEqual(g.nodes['"/detector"']['agnocast_node_type'], 'agnocast_node')

    # /topic_x edge should be agnocast
    for src, dst, key in g.edges:
      label = g.edges[src, dst, key].get('label', '').strip('"')
      if label == '/topic_x' and src == '"/node_a"' and dst == '"/node_b"':
        self.assertTrue(g.edges[src, dst, key]['is_agnocast'])

  def test_cli_failure_graceful(self):
    """When CLI fails completely, graph gets default attributes."""
    with patch.object(runtime.subprocess, 'run',
              side_effect=FileNotFoundError("ros2 not found")):
      g = _make_simple_graph()
      g = runtime.extend_agnocast_runtime(g)

    # All defaults
    for node_name in g.nodes:
      self.assertFalse(g.nodes[node_name]['has_agnocast'])
      self.assertFalse(g.nodes[node_name]['is_bridge_node'])
    for edge in g.edges:
      self.assertFalse(g.edges[edge]['is_agnocast'])

  def test_partial_failure_node_info(self):
    """When node info fails for one ③ node, others still work."""
    def side_effect(cmd, **kwargs):
      cmd_str = ' '.join(cmd)
      result = MagicMock()
      result.stderr = ''
      if 'node list_agnocast' in cmd_str:
        result.returncode = 0
        result.stdout = "/detector_a (Agnocast enabled)\n/detector_b (Agnocast enabled)\n"
        return result
      if 'node info_agnocast' in cmd_str:
        if 'detector_a' in cmd_str:
          result.returncode = 0
          result.stdout = "  Publishers:\n    /topic_x: msg/T (Agnocast enabled)\n  Subscribers:\n"
          return result
        else:
          # detector_b fails
          result.returncode = 1
          result.stdout = ''
          result.stderr = 'timeout'
          return result
      if 'topic list_agnocast' in cmd_str:
        result.returncode = 1  # topic list fails
        result.stdout = ''
        return result
      result.returncode = 1
      result.stdout = ''
      return result

    with patch.object(runtime.subprocess, 'run', side_effect=side_effect):
      g = _make_simple_graph()
      g = runtime.extend_agnocast_runtime(g)

    # detector_a should be added (its info succeeded)
    self.assertIn('"/detector_a"', g.nodes)
    # detector_b should also be added (node is added even if no edge info)
    self.assertIn('"/detector_b"', g.nodes)

  def test_bridge_pipeline(self):
    """Full pipeline with bridge nodes."""
    node_list_output = (
      "/sensing/lidar\n"
      "/agnocast_bridge_node_999 (Agnocast enabled)\n"
      "/planning/planner\n"
    )
    # topic list returns empty (simpler test)
    topic_list_output = ""
    with patch.object(runtime.subprocess, 'run',
              side_effect=self._mock_run({
                'node list_agnocast': node_list_output,
                'topic list_agnocast': topic_list_output,
              })):
      g = nx.MultiDiGraph()
      g.add_node('"/sensing/lidar"')
      g.add_node('"/agnocast_bridge_node_999"')
      g.add_node('"/planning/planner"')
      g.add_edge('"/sensing/lidar"', '"/agnocast_bridge_node_999"',
             label='/points_agnocast')
      g.add_edge('"/agnocast_bridge_node_999"', '"/planning/planner"',
             label='/points')
      g = runtime.extend_agnocast_runtime(g)

    # Bridge node detected
    self.assertTrue(g.nodes['"/agnocast_bridge_node_999"']['is_bridge_node'])

    # Synthesized edge exists
    found_bridged = False
    for edge in g.edges:
      if g.edges[edge].get('is_bridged', False):
        found_bridged = True
        self.assertEqual(g.edges[edge]['label_src'], '/points_agnocast')
        self.assertEqual(g.edges[edge]['label_dst'], '/points')
    self.assertTrue(found_bridged)


# ===========================================================================
# Helper tests
# ===========================================================================

class TestHelpers(unittest.TestCase):
  """Tests for helper functions."""

  def test_quote_name(self):
    self.assertEqual(runtime._quote_name('/node_a'), '"/node_a"')

  def test_extract_node_basename(self):
    self.assertEqual(runtime._extract_node_basename('/ns/node'), 'node')
    self.assertEqual(runtime._extract_node_basename('/node'), 'node')
    self.assertEqual(runtime._extract_node_basename('node'), 'node')

  def test_edge_exists(self):
    g = _make_simple_graph()
    self.assertTrue(runtime._edge_exists(g, '"/node_a"', '"/node_b"', '/topic_x'))
    self.assertFalse(runtime._edge_exists(g, '"/node_a"', '"/node_b"', '/topic_z'))
    self.assertFalse(runtime._edge_exists(g, '"/node_a"', '"/node_c"', '/topic_x'))

  def test_set_default_attributes(self):
    g = _make_simple_graph()
    runtime._set_default_attributes(g)
    for node_name in g.nodes:
      self.assertFalse(g.nodes[node_name]['has_agnocast'])
      self.assertFalse(g.nodes[node_name]['is_bridge_node'])
    for edge in g.edges:
      self.assertFalse(g.edges[edge]['is_agnocast'])
      self.assertFalse(g.edges[edge]['is_bridge_edge'])


if __name__ == '__main__':
  unittest.main()
