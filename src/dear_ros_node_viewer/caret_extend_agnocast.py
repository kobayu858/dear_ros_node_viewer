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
Function to extend graph with Agnocast attributes.
Adds is_agnocast/has_agnocast properties and bridge node handling.
"""

from __future__ import annotations
import json
import networkx as nx
import yaml
from .caret2networkx import quote_name
from .logger_factory import LoggerFactory

logger = LoggerFactory.create(__name__)

AGNOCAST_TOPIC_SUFFIX = '_agnocast'
BRIDGE_NODE_PREFIX = 'agnocast_bridge_node_'


def _mark_agnocast_edges(graph: nx.MultiDiGraph) -> None:
  """
  Mark edges as Agnocast or not based on topic name suffix.

  Sets is_agnocast = True on edges whose label ends with '_agnocast',
  False on all others.
  """
  for edge in graph.edges:
    label = graph.edges[edge].get('label', '')
    label_stripped = label.strip('"')
    is_agnocast = label_stripped.endswith(AGNOCAST_TOPIC_SUFFIX)
    graph.edges[edge]['is_agnocast'] = is_agnocast


def _mark_agnocast_nodes(graph: nx.MultiDiGraph) -> None:
  """
  Mark nodes that have at least one Agnocast edge.

  Sets has_agnocast = True on nodes connected to any is_agnocast edge,
  False on all others.
  """
  agnocast_nodes: set[str] = set()
  for edge in graph.edges:
    if graph.edges[edge].get('is_agnocast', False):
      agnocast_nodes.add(edge[0])
      agnocast_nodes.add(edge[1])

  for node_name in graph.nodes:
    graph.nodes[node_name]['has_agnocast'] = node_name in agnocast_nodes


def _mark_bridge_nodes(graph: nx.MultiDiGraph) -> None:
  """
  Identify bridge nodes by name pattern and mark them.

  Bridge nodes have names matching 'agnocast_bridge_node_*'.
  Sets is_bridge_node = True/False on each node.
  Sets is_bridge_edge = True on edges connected to bridge nodes, False otherwise.
  """
  for node_name in graph.nodes:
    node_name_stripped = node_name.strip('"')
    # Node name may have leading / or namespace like /ns/agnocast_bridge_node_123
    # Extract the last component of the path for prefix matching
    base_name = node_name_stripped.rsplit('/', 1)[-1]
    is_bridge = base_name.startswith(BRIDGE_NODE_PREFIX)
    graph.nodes[node_name]['is_bridge_node'] = is_bridge

  for edge in graph.edges:
    src_is_bridge = graph.nodes[edge[0]].get('is_bridge_node', False)
    dst_is_bridge = graph.nodes[edge[1]].get('is_bridge_node', False)
    graph.edges[edge]['is_bridge_edge'] = src_is_bridge or dst_is_bridge


def _synthesize_bridge_direct_edges(graph: nx.MultiDiGraph) -> None:
  """
  Synthesize direct edges that bypass bridge nodes.

  For each bridge node, connect its upstream node(s) directly to its
  downstream node(s) with is_agnocast=True, is_bridged=True.
  These direct edges are used when Show Bridge is OFF.
  """
  bridge_nodes = [n for n in graph.nodes
          if graph.nodes[n].get('is_bridge_node', False)]

  for bridge_node in bridge_nodes:
    # Collect upstream nodes (nodes that publish to this bridge)
    upstream_edges = [(e, graph.edges[e]) for e in graph.edges
             if e[1] == bridge_node]
    # Collect downstream nodes (nodes that this bridge publishes to)
    downstream_edges = [(e, graph.edges[e]) for e in graph.edges
              if e[0] == bridge_node]

    for up_edge, up_data in upstream_edges:
      upstream_node = up_edge[0]
      for down_edge, down_data in downstream_edges:
        downstream_node = down_edge[1]
        label_src = up_data.get('label', '')
        label_dst = down_data.get('label', '')
        # Use upstream label as the canonical label (for edge display text),
        # but store both so add_link_in_dpg can find the correct attribute
        # slot on each side (publisher has _agnocast topic, subscriber has
        # the original topic name).
        graph.add_edge(
          upstream_node, downstream_node,
          label=label_src,
          label_src=label_src,
          label_dst=label_dst,
          is_agnocast=True,
          is_bridged=True,
          is_bridge_edge=False,
        )
        logger.debug(
          'Synthesized direct edge: %s -> %s (src=%s, dst=%s)',
          upstream_node, downstream_node, label_src, label_dst)


def load_agnocast_info(agnocast_file: str) -> dict | None:
  """
  Load agnocast_info.json (optional supplementary file).

  Parameters
  ----------
  agnocast_file : str
    Path to agnocast_info.json

  Returns
  -------
  dict | None
    Parsed JSON content, or None if file is invalid/missing
  """
  if agnocast_file is None:
    return None

  try:
    with open(agnocast_file, encoding='UTF-8') as f:
      info = json.load(f)
  except FileNotFoundError:
    logger.warning('Agnocast info file not found: %s', agnocast_file)
    return None
  except json.JSONDecodeError as e:
    logger.warning('Failed to parse agnocast info file: %s (%s)', agnocast_file, e)
    return None

  version = info.get('version', 1)
  if version != 1:
    logger.warning(
      'Unsupported agnocast_info.json version: %s (expected 1). Ignoring file.',
      version)
    return None

  if 'agnocast_nodes' not in info:
    logger.warning('agnocast_info.json missing "agnocast_nodes" field. Ignoring file.')
    return None

  return info


def _mark_agnocast_node_types(graph: nx.MultiDiGraph, agnocast_info: dict) -> None:
  """
  Set agnocast_node_type based on supplementary file.

  Types:
    'agnocast_node'        — listed in agnocast_nodes (③)
    'rclcpp_with_agnocast' — not listed but has_agnocast is True (②)
    'rclcpp_only'          — has_agnocast is False (①)
  """
  agnocast_node_set = set()
  for name in agnocast_info.get('agnocast_nodes', []):
    agnocast_node_set.add(quote_name(name))

  for node_name in graph.nodes:
    if node_name in agnocast_node_set:
      graph.nodes[node_name]['agnocast_node_type'] = 'agnocast_node'
    elif graph.nodes[node_name].get('has_agnocast', False):
      graph.nodes[node_name]['agnocast_node_type'] = 'rclcpp_with_agnocast'
    else:
      graph.nodes[node_name]['agnocast_node_type'] = 'rclcpp_only'


def extend_agnocast(filename: str,
          graph: nx.MultiDiGraph,
          agnocast_file: str | None = None) -> nx.MultiDiGraph:
  """
  Add Agnocast attributes to a graph.

  Processing steps:
    1. Mark edges with is_agnocast based on '_agnocast' topic suffix
    2. Mark nodes with has_agnocast based on connected edges
    3. Identify bridge nodes by name pattern
    4. Synthesize direct edges for bridge bypass (Show Bridge OFF)
    5. (Optional) Set agnocast_node_type from supplementary JSON

  Parameters
  ----------
  filename : str
    Path to architecture.yaml (used for YAML-based detection)
  graph : nx.MultiDiGraph
    Graph to extend (modified in-place)
  agnocast_file : str | None
    Path to agnocast_info.json (optional)

  Returns
  -------
  nx.MultiDiGraph
    The same graph with Agnocast attributes added
  """
  # Step 1: Mark edges
  _mark_agnocast_edges(graph)

  # Step 2: Mark nodes
  _mark_agnocast_nodes(graph)

  # Step 3: Mark bridge nodes and edges
  _mark_bridge_nodes(graph)

  # Step 4: Synthesize direct edges for bridge bypass
  _synthesize_bridge_direct_edges(graph)

  # Step 5: (Optional) Set node types from supplementary file
  agnocast_info = load_agnocast_info(agnocast_file)
  if agnocast_info is not None:
    _mark_agnocast_node_types(graph, agnocast_info)
    logger.info('Agnocast node types set from: %s', agnocast_file)
  else:
    logger.info('No agnocast info file; node type classification skipped')

  # Log summary
  agnocast_edge_count = sum(
    1 for e in graph.edges if graph.edges[e].get('is_agnocast', False))
  agnocast_node_count = sum(
    1 for n in graph.nodes if graph.nodes[n].get('has_agnocast', False))
  bridge_node_count = sum(
    1 for n in graph.nodes if graph.nodes[n].get('is_bridge_node', False))
  bridged_edge_count = sum(
    1 for e in graph.edges if graph.edges[e].get('is_bridged', False))

  logger.info(
    'Agnocast extend: %d agnocast edges, %d agnocast nodes, '
    '%d bridge nodes, %d synthesized direct edges',
    agnocast_edge_count, agnocast_node_count,
    bridge_node_count, bridged_edge_count)

  return graph
