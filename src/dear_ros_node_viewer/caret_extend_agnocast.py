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
import networkx as nx
import yaml
try:
  from yaml import CSafeLoader as SafeLoader
except ImportError:
  from yaml import SafeLoader
from .caret2networkx import quote_name
from .logger_factory import LoggerFactory
from .agnocast_extend_utils import (
  BRIDGE_NODE_PREFIX,
  AGNOCAST_TOPIC_SUFFIX,
  mark_bridge_nodes,
  synthesize_bridge_direct_edges,
)

logger = LoggerFactory.create(__name__)

AGNOCAST_ONLY_EXECUTOR_PREFIX = 'agnocast_only_'


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


def _mark_agnocast_node_types(graph: nx.MultiDiGraph, filename: str) -> None:
  with open(filename, encoding='UTF-8') as f:
    arch = yaml.load(f, Loader=SafeLoader)

  agnocast_only_cbg_names: set[str] = set()
  for executor in arch.get('executors', []):
    executor_type = executor.get('executor_type', '')
    if executor_type.startswith(AGNOCAST_ONLY_EXECUTOR_PREFIX):
      for cbg_name in executor.get('callback_group_names', []):
        agnocast_only_cbg_names.add(cbg_name)

  agnocast_only_nodes: set[str] = set()
  for node in arch.get('nodes', []):
    for cbg in node.get('callback_groups', []):
      cbg_name = cbg.get('callback_group_name', '')
      if cbg_name in agnocast_only_cbg_names:
        agnocast_only_nodes.add(quote_name(node['node_name']))

  for node_name in graph.nodes:
    graph.nodes[node_name]['is_agnocast_node'] = node_name in agnocast_only_nodes



def extend_agnocast(filename: str,
          graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
  """
  Add Agnocast attributes to a graph.

  Processing steps:
    1. Mark edges with is_agnocast based on '_agnocast' topic suffix
    2. Set agnocast_node_type from executor_type in architecture YAML
    3. Identify bridge nodes by name pattern
    4. Synthesize direct edges for bridge bypass (Show Bridge OFF)

  Parameters
  ----------
  filename : str
    Path to architecture.yaml
  graph : nx.MultiDiGraph
    Graph to extend (modified in-place)

  Returns
  -------
  nx.MultiDiGraph
    The same graph with Agnocast attributes added
  """
  # Step 1: Mark edges
  _mark_agnocast_edges(graph)

  # Step 2: Set node types from executor_type in YAML
  _mark_agnocast_node_types(graph, filename)

  # Step 3: Mark bridge nodes and edges
  mark_bridge_nodes(graph)

  # Step 4: Synthesize direct edges for bridge bypass
  # upgrade_existing_edges=False: YAML-derived edges only, no prior agnocast edges exist
  synthesize_bridge_direct_edges(graph, upgrade_existing_edges=False)

  # Log summary
  agnocast_edge_count = sum(
    1 for e in graph.edges if graph.edges[e].get('is_agnocast', False))
  agnocast_node_count = sum(
      1 for n in graph.nodes
      if graph.nodes[n].get('is_agnocast_node', False))
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
