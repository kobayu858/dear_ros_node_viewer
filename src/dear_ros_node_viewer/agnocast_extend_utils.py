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
Shared utilities for Agnocast graph processing.

Used by both caret_extend_agnocast.py (static/YAML input) and
agnocast_extend_runtime.py (dynamic/CLI input).
"""

from __future__ import annotations
import networkx as nx
from .logger_factory import LoggerFactory

logger = LoggerFactory.create(__name__)

BRIDGE_NODE_PREFIX = 'agnocast_bridge_node_'
AGNOCAST_TOPIC_SUFFIX = '_agnocast'

# --- Agnocast attribute names (single source of truth) --------------------
# Used by dot2networkx (read) and graph_manager/save_agnocast_dot (write).
AGNOCAST_NODE_ATTRS = ('agnocast_node_type', 'is_bridge_node')
AGNOCAST_EDGE_ATTRS = ('is_agnocast', 'is_bridge_edge', 'is_bridged',
                       'label_src', 'label_dst')

# Attributes that are bool in the NetworkX graph but stored as strings in dot.
_AGNOCAST_BOOL_ATTRS = frozenset({
  'is_bridge_node', 'is_agnocast', 'is_bridge_edge', 'is_bridged',
})


def coerce_dot_attr(key: str, value: str) -> object:
  """Convert a dot attribute value to its proper Python type.

  Dot files store every attribute as a string.  This helper converts
  known boolean attributes back to ``bool`` so that downstream code
  (e.g. ``edge_data.get('is_agnocast', False)``) works correctly —
  the string ``"False"`` is truthy in Python and would otherwise cause
  every edge to appear as Agnocast.
  """
  stripped = value.strip('"')
  if key in _AGNOCAST_BOOL_ATTRS:
    return stripped == 'True'
  return stripped


def base_topic(label: str) -> str:
  """Return the topic name with the Agnocast suffix stripped.

  Examples
  --------
  ``'"/sensing/lidar_agnocast"'`` → ``'/sensing/lidar'``
  ``'/chatter_agnocast'``         → ``'/chatter'``
  ``'/chatter'``                  → ``'/chatter'``
  """
  return label.strip('"').removesuffix(AGNOCAST_TOPIC_SUFFIX)


def extract_node_basename(node_name: str) -> str:
  """Get the basename from a fully-qualified or quoted node name.
  
  Examples
  --------
  ``'"/ns/node"'`` → ``'node'``
  ``'/ns/node'``   → ``'node'``
  """
  bare = node_name.strip('"')
  return bare.rsplit('/', 1)[-1] if '/' in bare else bare


def mark_bridge_nodes(graph: nx.MultiDiGraph) -> None:
  """Mark every node and edge with bridge-related flags.

  Sets on each node:
    ``is_bridge_node`` : bool — True when the node's basename matches
    ``agnocast_bridge_node_*``.

  Sets on each edge:
    ``is_bridge_edge`` : bool — True when either endpoint is a bridge node.
  """
  for node_name in graph.nodes:
    basename = extract_node_basename(node_name)
    graph.nodes[node_name]['is_bridge_node'] = basename.startswith(BRIDGE_NODE_PREFIX)

  for edge in graph.edges:
    src_is_bridge = graph.nodes[edge[0]].get('is_bridge_node', False)
    dst_is_bridge = graph.nodes[edge[1]].get('is_bridge_node', False)
    graph.edges[edge]['is_bridge_edge'] = src_is_bridge or dst_is_bridge


def synthesize_bridge_direct_edges(graph: nx.MultiDiGraph,
                                   upgrade_existing_edges: bool = False) -> None:
  """Synthesize direct edges that bypass bridge nodes.

  For each bridge node, pairs of (upstream node, downstream node) whose
  base topic names match are connected with a synthesized edge
  (``is_bridged=True``, ``is_bridge_edge=False``).
  These direct edges are shown when "Show Bridge" is OFF.

  Must be called after ``mark_bridge_nodes()``.

  Parameters
  ----------
  graph : nx.MultiDiGraph
      Graph with ``is_bridge_node`` already set on all nodes.
  upgrade_existing_edges : bool
      When True, an edge that already exists with the same src/dst/label
      is upgraded in-place with bridge attributes instead of adding a new
      edge.
  """
  bridge_nodes = [n for n in graph.nodes
                  if graph.nodes[n].get('is_bridge_node', False)]

  edges_to_add: list[dict] = []
  for bridge_node in bridge_nodes:
    # NetworkXの機能を使って、ブリッジノードに直接繋がるエッジのみを取得 (O(degree)で済む)
    upstream_edges = graph.in_edges(bridge_node, data=True)
    downstream_edges = graph.out_edges(bridge_node, data=True)

    upstream = [(u, data.get('label', '')) for u, _, data in upstream_edges]
    downstream = [(v, data.get('label', '')) for _, v, data in downstream_edges]

    for src, label_src in upstream:
      for dst, label_dst in downstream:
        if base_topic(label_src) != base_topic(label_dst):
          continue
        edges_to_add.append({
          'src': src, 'dst': dst,
          'label_src': label_src,
          'label_dst': label_dst,
        })

  for e in edges_to_add:
    label_dst_bare = e['label_dst'].strip('"')

    existing_key = None
    if upgrade_existing_edges and graph.has_edge(e['src'], e['dst']):
      # 指定した src -> dst のエッジデータのみを取得
      edge_data = graph.get_edge_data(e['src'], e['dst'])
      if edge_data:
        for key, data in edge_data.items():
          edge_label = data.get('label', '').strip('"')
          if edge_label == label_dst_bare:
            existing_key = key
            break

    if existing_key is not None:
      # Upgrade existing edge to synthesized bridge edge
      graph.edges[e['src'], e['dst'], existing_key].update({
        'label_src': e['label_src'],
        'label_dst': e['label_dst'],
        'is_agnocast': True,
        'is_bridged': True,
        'is_bridge_edge': False,
      })
      logger.debug(
        'Upgraded existing edge to bridged: %s -> %s (label=%s)',
        e['src'], e['dst'], e['label_dst'])
    else:
      graph.add_edge(
        e['src'], e['dst'],
        label=e['label_dst'],
        label_src=e['label_src'],
        label_dst=e['label_dst'],
        is_agnocast=True,
        is_bridged=True,
        is_bridge_edge=False,
      )
      logger.debug(
        'Synthesized direct edge: %s -> %s (src=%s, dst=%s)',
        e['src'], e['dst'], e['label_src'], e['label_dst'])
