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
Function to create NetworkX object from dot graph file (rosgraph.dot)
"""

from __future__ import annotations
import networkx as nx
import matplotlib.pyplot as plt
import pydot

from .logger_factory import LoggerFactory
from .caret2networkx import make_graph_from_topic_association
from .agnocast_extend_utils import (
  AGNOCAST_NODE_ATTRS,
  AGNOCAST_EDGE_ATTRS,
  parse_dot_bool_attr,
)

logger = LoggerFactory.create(__name__)


def dot2networkx_nodeonly(graph_org: nx.classes.digraph.DiGraph,
              display_unconnected_nodes=False) -> nx.classes.digraph.DiGraph:
  """Create NetworkX Object from dot graph file (nodes only) by rqt_graph"""
  graph = nx.MultiDiGraph()
  for node_org in graph_org.nodes:
    if 'label' not in graph_org.nodes[node_org]:
      continue
    label = graph_org.nodes[node_org]['label']
    if display_unconnected_nodes:
      graph.add_node(label)
    # Agnocast node attributes (present when loaded from an Agnocast-annotated dot)
    node_data = graph_org.nodes[node_org]
    agnocast_node_attrs = {
      attr: parse_dot_bool_attr(attr, node_data[attr])
      for attr in AGNOCAST_NODE_ATTRS
      if attr in node_data
    }
    if agnocast_node_attrs:
      graph.add_node(label, **agnocast_node_attrs)

  for edge in graph_org.edges:
    if 'label' not in graph_org.nodes[edge[0]] or 'label' not in graph_org.nodes[edge[1]] or 'label' not in graph_org.edges[edge]:
      continue
    node_pub = graph_org.nodes[edge[0]]['label']
    node_sub = graph_org.nodes[edge[1]]['label']
    label = graph_org.edges[edge]['label']
    # Agnocast edge attributes (present when loaded from an Agnocast-annotated dot)
    edge_data = graph_org.edges[edge]
    agnocast_edge_attrs = {
      attr: parse_dot_bool_attr(attr, edge_data[attr])
      for attr in AGNOCAST_EDGE_ATTRS
      if attr in edge_data
    }
    graph.add_edge(node_pub, node_sub, label=label, **agnocast_edge_attrs)

  return graph


def dot2networkx_nodetopic(graph_org: nx.classes.digraph.DiGraph,
               display_unconnected_nodes=False,
               display_unconnected_topics=False) -> nx.classes.digraph.DiGraph:
  """Create NetworkX Object from dot graph file (nodes / topics) by rqt_graph"""

  # "/topic_0": ["/node_0", ], <- publishers of /topic_0 are ["/node_0", ] #
  topic_pub_dict: dict[str, list[str]] = {}

  # "/topic_0": ["/node_1", ], <- subscribers of /topic_0 are ["/node_1", ] #
  topic_sub_dict: dict[str, list[str]] = {}

  # Node-to-node edges (both endpoints are 'ellipse' nodes, not a topic 'box').
  # save_agnocast_dot() writes edges in this form, bypassing the topic/box nodes
  # rqt_graph uses, so they never appear in topic_pub_dict/topic_sub_dict above.
  direct_edges: list[tuple[str, str, dict]] = []

  for edge in graph_org.edges:
    src = graph_org.nodes[edge[0]]
    dst = graph_org.nodes[edge[1]]
    if not ('label' in src and 'label' in dst and 'shape' in src and 'shape' in dst):
      continue
    src_name = src['label']
    dst_name = dst['label']
    src_is_node = bool(src['shape'] == 'ellipse')
    dst_is_node = bool(dst['shape'] == 'ellipse')

    if src_is_node is True and dst_is_node is False:
      if dst_name in topic_pub_dict:
        topic_pub_dict[dst_name].append(src_name)
      else:
        topic_pub_dict[dst_name] = [src_name]
    elif src_is_node is False and dst_is_node is True:
      if src_name in topic_sub_dict:
        topic_sub_dict[src_name].append(dst_name)
      else:
        topic_sub_dict[src_name] = [dst_name]
    elif src_is_node is True and dst_is_node is True:
      direct_edges.append((src_name, dst_name, graph_org.edges[edge]))

  graph = make_graph_from_topic_association(topic_pub_dict, topic_sub_dict,
                       display_unconnected_topics)

  if display_unconnected_nodes:
    for node_id in graph_org.nodes:
      node_data = graph_org.nodes[node_id]
      if 'label' in node_data and node_data.get('shape') == 'ellipse':
        graph.add_node(node_data['label'])

  # Restore Agnocast node attributes (present when loaded from an Agnocast-annotated dot)
  for node_id in graph_org.nodes:
    node_data = graph_org.nodes[node_id]
    if node_data.get('shape') != 'ellipse' or 'label' not in node_data:
      continue
    agnocast_node_attrs = {
      attr: parse_dot_bool_attr(attr, node_data[attr])
      for attr in AGNOCAST_NODE_ATTRS
      if attr in node_data
    }
    if agnocast_node_attrs:
      graph.add_node(node_data['label'], **agnocast_node_attrs)

  # Restore Agnocast edge attributes from the node-to-node edges collected above.
  # An equivalent edge may already exist (reconstructed from topic association);
  # merge into it instead of duplicating when so, otherwise add it as a new edge
  # (e.g. a bridge edge whose Agnocast-only endpoint never appears via a topic node).
  for src_name, dst_name, edge_data in direct_edges:
    agnocast_edge_attrs = {
      attr: parse_dot_bool_attr(attr, edge_data[attr])
      for attr in AGNOCAST_EDGE_ATTRS
      if attr in edge_data
    }
    label = edge_data.get('label', '')
    existing_key = None
    for key, data in graph.get_edge_data(src_name, dst_name, default={}).items():
      if data.get('label', '') == label:
        existing_key = key
        break
    if existing_key is not None:
      graph.edges[src_name, dst_name, existing_key].update(agnocast_edge_attrs)
    else:
      graph.add_edge(src_name, dst_name, label=label, **agnocast_edge_attrs)

  return graph


def parse_dot_file(filename: str) -> pydot.Dot:
  """Parse a dot file into a pydot.Dot object.

  Exposed so callers that also need pydot-level access to the same file
  (e.g. save_agnocast_dot) can reuse this parse instead of re-reading and
  re-parsing the file from disk a second time.
  """
  graphs = pydot.graph_from_dot_file(filename)
  return graphs[0]


def dot2networkx(filename: str, display_unconnected_nodes=False,
         display_unconnected_topics=False,
         pydot_graph: pydot.Dot | None = None) -> nx.classes.digraph.DiGraph:
  """Function to create NetworkX object from dot graph file (rosgraph.dot)

  Parameters
  ----------
  pydot_graph : pydot.Dot | None
      Already-parsed pydot graph for ``filename``, to avoid re-parsing it.
      When ``None``, this function parses ``filename`` itself.
  """
  if pydot_graph is None:
    pydot_graph = parse_dot_file(filename)
  graph_org = nx.MultiDiGraph(nx.drawing.nx_pydot.from_pydot(pydot_graph))

  is_node_only = True
  for node_org in graph_org.nodes:
    if 'shape' in graph_org.nodes[node_org]:
      if graph_org.nodes[node_org]['shape'] == 'box':
        is_node_only = False
        break

  if is_node_only:
    graph = dot2networkx_nodeonly(graph_org, display_unconnected_nodes)
  else:
    graph = dot2networkx_nodetopic(graph_org, display_unconnected_nodes,
                   display_unconnected_topics)

  logger.info('len(connected_nodes) = %d', len(graph.nodes))

  return graph


if __name__ == '__main__':
  def local_main():
    """main function for this file"""
    graph = dot2networkx('rosgraph_nodeonly.dot')
    pos = nx.spring_layout(graph)
    # pos = nx.circular_layout(graph)
    nx.draw_networkx(graph, pos)
    plt.show()

  local_main()
