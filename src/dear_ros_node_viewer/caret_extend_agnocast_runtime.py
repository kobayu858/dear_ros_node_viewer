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
Function to extend graph with Agnocast attributes from runtime CLI.

This module adds Agnocast visualization attributes to a NetworkX graph
by querying the running ROS 2 system via Agnocast CLI commands.
It is the Phase 2 (dynamic input) counterpart of caret_extend_agnocast.py (Phase 1).

The same graph attribute names are used so that graph_view.py / graph_viewmodel.py
require zero changes.
"""

from __future__ import annotations
import subprocess
from dataclasses import dataclass, field
import networkx as nx
from .logger_factory import LoggerFactory

logger = LoggerFactory.create(__name__)

BRIDGE_NODE_PREFIX = 'agnocast_bridge_node_'


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EndpointInfo:
  """A single Agnocast endpoint returned by CLI."""
  node_name: str   # fully-qualified name, e.g. "/sensing/lidar_driver"
  is_bridge: bool  # True if the node is a bridge node


@dataclass
class TopicEndpoints:
  """Agnocast endpoints for one topic."""
  agnocast_pubs: list[EndpointInfo] = field(default_factory=list)
  agnocast_subs: list[EndpointInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _run_agnocast_command(cmd: list[str], timeout: int = 15) -> str | None:
  """Run an Agnocast CLI command and return stdout, or None on failure."""
  try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
      logger.warning('Agnocast command failed (rc=%d): %s\nstderr: %s',
               result.returncode, ' '.join(cmd), result.stderr.strip())
      return None
    return result.stdout
  except FileNotFoundError:
    logger.warning('ros2 command not found. Agnocast features disabled.')
    return None
  except subprocess.TimeoutExpired:
    logger.warning('Agnocast command timed out (%ds): %s', timeout, ' '.join(cmd))
    return None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_node_list_agnocast(output: str) -> tuple[set[str], set[str]]:
  """Parse ``ros2 node list_agnocast`` output.

  Returns
  -------
  agnocast_only_nodes : set[str]
      Nodes with ``(Agnocast enabled)`` — these are type-③ nodes.
  all_nodes : set[str]
      All nodes listed.
  """
  agnocast_only_nodes: set[str] = set()
  all_nodes: set[str] = set()
  for line in output.strip().splitlines():
    line = line.strip()
    if not line:
      continue
    node_name = line.split(' ')[0]
    all_nodes.add(node_name)
    if '(Agnocast enabled)' in line:
      agnocast_only_nodes.add(node_name)
  return agnocast_only_nodes, all_nodes


def _parse_node_info_agnocast(output: str) -> tuple[set[str], set[str]]:
  """Parse ``ros2 node info_agnocast <node>`` output.

  Returns
  -------
  pub_topics : set[str]
      Topics this node publishes via Agnocast.
  sub_topics : set[str]
      Topics this node subscribes via Agnocast.
  """
  pub_topics: set[str] = set()
  sub_topics: set[str] = set()
  current_section: str | None = None

  for line in output.strip().splitlines():
    stripped = line.strip()

    # Detect section headers
    if stripped.startswith('Publishers:') or stripped.startswith('Agnocast Publishers:'):
      current_section = 'pub'
      continue
    if stripped.startswith('Subscribers:') or stripped.startswith('Agnocast Subscribers:'):
      current_section = 'sub'
      continue
    if stripped.startswith('Service Servers:') or stripped.startswith('Service Clients:') \
        or stripped.startswith('Action Servers:') or stripped.startswith('Action Clients:'):
      current_section = None
      continue

    # Collect Agnocast topic names (lines starting with '/' and tagged)
    if current_section and stripped.startswith('/') and '(Agnocast' in stripped:
      topic = stripped.split(':')[0].strip()
      if current_section == 'pub':
        pub_topics.add(topic)
      else:
        sub_topics.add(topic)

  return pub_topics, sub_topics


def _parse_topic_list_agnocast(output: str) -> set[str]:
  """Parse ``ros2 topic list_agnocast`` output.

  Returns set of Agnocast-enabled topic names.
  """
  agnocast_topics: set[str] = set()
  for line in output.strip().splitlines():
    line = line.strip()
    if not line:
      continue
    topic = line.split(' ')[0]
    if '(Agnocast' in line:
      agnocast_topics.add(topic)
  return agnocast_topics


def _extract_node_basename(full_name: str) -> str:
  """Get the basename from a fully-qualified node name.

  Example: ``"/ns/node"`` → ``"node"``
  """
  return full_name.rsplit('/', 1)[-1]


def _parse_single_topic_info(block: str) -> TopicEndpoints:
  """Parse one topic block from ``ros2 topic info_agnocast -v`` output."""
  endpoints = TopicEndpoints()
  current_section: str | None = None
  last_node_name: str | None = None
  last_namespace: str | None = None

  for line in block.strip().splitlines():
    stripped = line.strip()

    if stripped.startswith('Agnocast Publisher count:'):
      current_section = 'pub'
    elif stripped.startswith('Agnocast Subscription count:'):
      current_section = 'sub'
    elif stripped.startswith('ROS 2 Publisher count:'):
      current_section = None
    elif stripped.startswith('ROS 2 Subscription count:'):
      current_section = None
    elif stripped.startswith('Node name:'):
      last_node_name = stripped.split(':', 1)[1].strip()
    elif stripped.startswith('Node namespace:'):
      last_namespace = stripped.split(':', 1)[1].strip()
    elif 'Agnocast enabled' in stripped and current_section:
      if last_namespace is not None and last_node_name is not None:
        full_name = last_namespace.rstrip('/') + '/' + last_node_name
        is_bridge = _extract_node_basename(full_name).startswith(BRIDGE_NODE_PREFIX)
        info = EndpointInfo(node_name=full_name, is_bridge=is_bridge)
        if current_section == 'pub':
          endpoints.agnocast_pubs.append(info)
        else:
          endpoints.agnocast_subs.append(info)

  return endpoints


def _parse_all_topic_info_agnocast(output: str) -> dict[str, TopicEndpoints]:
  """Parse ``ros2 topic info_agnocast --all -v`` output.

  Splits on ``--- /topic_name ---`` separators and delegates each block
  to :func:`_parse_single_topic_info`.
  """
  result: dict[str, TopicEndpoints] = {}
  current_topic: str | None = None
  current_block_lines: list[str] = []

  for line in output.splitlines():
    stripped = line.strip()
    if stripped.startswith('--- ') and stripped.endswith(' ---'):
      # Flush previous block
      if current_topic is not None and current_block_lines:
        block = '\n'.join(current_block_lines)
        result[current_topic] = _parse_single_topic_info(block)
      current_topic = stripped[4:-4].strip()
      current_block_lines = []
    else:
      current_block_lines.append(line)

  # Flush last block
  if current_topic is not None and current_block_lines:
    block = '\n'.join(current_block_lines)
    result[current_topic] = _parse_single_topic_info(block)

  return result


# ---------------------------------------------------------------------------
# CLI fetchers
# ---------------------------------------------------------------------------

def _fetch_node_list() -> tuple[set[str], set[str]] | None:
  """Execute ``ros2 node list_agnocast`` and return parsed result."""
  output = _run_agnocast_command(['ros2', 'node', 'list_agnocast'])
  if output is None:
    return None
  return _parse_node_list_agnocast(output)


def _fetch_node_info(node_name: str) -> tuple[set[str], set[str]] | None:
  """Execute ``ros2 node info_agnocast <node>`` and return parsed result."""
  output = _run_agnocast_command(['ros2', 'node', 'info_agnocast', node_name])
  if output is None:
    return None
  return _parse_node_info_agnocast(output)


def _fetch_all_topic_info() -> dict[str, TopicEndpoints] | None:
  """Execute ``ros2 topic info_agnocast -v`` per topic and return parsed result.

  Queries each Agnocast topic individually with ``-v`` to obtain
  per-node endpoint information.
  """
  topic_list_output = _run_agnocast_command(['ros2', 'topic', 'list_agnocast'])
  if topic_list_output is None:
    return None

  agnocast_topics = _parse_topic_list_agnocast(topic_list_output)
  all_info: dict[str, TopicEndpoints] = {}
  for topic in agnocast_topics:
    output = _run_agnocast_command(
      ['ros2', 'topic', 'info_agnocast', '-v', topic]
    )
    if output is not None:
      all_info[topic] = _parse_single_topic_info(output)
  return all_info if all_info else None


# ---------------------------------------------------------------------------
# Node name helpers
# ---------------------------------------------------------------------------

def _quote_name(name: str) -> str:
  """Convert a CLI node name to the dot2networkx quoted format.

  Example: ``"/sensing/lidar"`` → ``'"/sensing/lidar"'``
  """
  return '"' + name + '"'


def _edge_exists(graph: nx.MultiDiGraph,
         src: str, dst: str, topic: str) -> bool:
  """Check if an edge with the given topic label already exists."""
  if graph.has_edge(src, dst):
    for key in graph[src][dst]:
      label = graph[src][dst][key].get('label', '').strip('"')
      if label == topic:
        return True
  return False


# ---------------------------------------------------------------------------
# Graph modification: add ③ nodes
# ---------------------------------------------------------------------------

def _build_topic_node_maps(graph: nx.MultiDiGraph
               ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
  """Build topic→publisher and topic→subscriber maps from existing edges.

  Returns
  -------
  topic_to_publishers : dict[str, set[str]]
      ``{topic_name: {quoted_node_name, ...}}``
  topic_to_subscribers : dict[str, set[str]]
      ``{topic_name: {quoted_node_name, ...}}``
  """
  topic_to_publishers: dict[str, set[str]] = {}
  topic_to_subscribers: dict[str, set[str]] = {}

  for src, dst, key in graph.edges:
    label = graph.edges[src, dst, key].get('label', '').strip('"')
    if not label:
      continue
    topic_to_publishers.setdefault(label, set()).add(src)
    topic_to_subscribers.setdefault(label, set()).add(dst)

  return topic_to_publishers, topic_to_subscribers


def _add_edges_for_node(graph: nx.MultiDiGraph,
            quoted_node: str,
            pub_topics: set[str],
            sub_topics: set[str],
            topic_to_publishers: dict[str, set[str]],
            topic_to_subscribers: dict[str, set[str]]):
  """Add edges between a ③ node and existing nodes via topic matching.

  - ③ publishes → edges to existing subscribers
  - ③ subscribes → edges from existing publishers
  """
  for topic in pub_topics:
    for sub_node in topic_to_subscribers.get(topic, set()):
      if sub_node == quoted_node:
        continue
      if not _edge_exists(graph, quoted_node, sub_node, topic):
        graph.add_edge(quoted_node, sub_node,
                label=topic, is_agnocast=True)

  for topic in sub_topics:
    for pub_node in topic_to_publishers.get(topic, set()):
      if pub_node == quoted_node:
        continue
      if not _edge_exists(graph, pub_node, quoted_node, topic):
        graph.add_edge(pub_node, quoted_node,
                label=topic, is_agnocast=True)


def _add_agnocast_nodes(graph: nx.MultiDiGraph,
            agnocast_only_nodes: set[str],
            node_topics: dict[str, tuple[set[str], set[str]]],
            topic_endpoints: dict[str, TopicEndpoints] | None = None
            ) -> nx.MultiDiGraph:
  """Add type-③ nodes (agnocast::Node) and their edges to the graph.

  Parameters
  ----------
  graph : nx.MultiDiGraph
      Existing graph built from dot2networkx.
  agnocast_only_nodes : set[str]
      Fully-qualified names of ③ nodes from ``ros2 node list_agnocast``.
  node_topics : dict
      ``{node_name: (pub_topics, sub_topics)}`` from ``ros2 node info_agnocast``.
  topic_endpoints : dict, optional
      Per-topic endpoint info from ``ros2 topic info_agnocast -v``.
      Used to register ② nodes' Agnocast pub/sub into the maps.
  """
  # Build maps from existing edges (dot2networkx graph)
  topic_to_publishers, topic_to_subscribers = _build_topic_node_maps(graph)

  # Register ② nodes' Agnocast endpoints (not in .dot but known from CLI)
  if topic_endpoints is not None:
    for topic, endpoints in topic_endpoints.items():
      for ep in endpoints.agnocast_pubs:
        if not ep.is_bridge:
          quoted = _quote_name(ep.node_name)
          topic_to_publishers.setdefault(topic, set()).add(quoted)
      for ep in endpoints.agnocast_subs:
        if not ep.is_bridge:
          quoted = _quote_name(ep.node_name)
          topic_to_subscribers.setdefault(topic, set()).add(quoted)

  # Phase 1: Add all ③ nodes and register their topics into the maps
  nodes_to_connect: list[tuple[str, set[str], set[str]]] = []
  for node_name in agnocast_only_nodes:
    if _extract_node_basename(node_name).startswith(BRIDGE_NODE_PREFIX):
      continue

    quoted_name = _quote_name(node_name)

    # Skip if already present (could be a ② node visible in .dot)
    if quoted_name in graph.nodes:
      continue

    graph.add_node(quoted_name)
    logger.debug('Added ③ node: %s', node_name)

    if node_name in node_topics:
      pub_topics, sub_topics = node_topics[node_name]
      # Register into maps so other ③ nodes can find this node
      for topic in pub_topics:
        topic_to_publishers.setdefault(topic, set()).add(quoted_name)
      for topic in sub_topics:
        topic_to_subscribers.setdefault(topic, set()).add(quoted_name)
      nodes_to_connect.append((quoted_name, pub_topics, sub_topics))

  # Phase 2: Add edges (now all ③ nodes are in the maps)
  for quoted_name, pub_topics, sub_topics in nodes_to_connect:
    _add_edges_for_node(graph, quoted_name,
              pub_topics, sub_topics,
              topic_to_publishers, topic_to_subscribers)

  return graph


# ---------------------------------------------------------------------------
# Graph modification: mark existing edges
# ---------------------------------------------------------------------------

def _mark_agnocast_edges(graph: nx.MultiDiGraph,
             topic_endpoints: dict[str, TopicEndpoints] | None
             ) -> nx.MultiDiGraph:
  """Set ``is_agnocast`` attribute on every edge.

  Uses endpoint information to determine whether an edge's
  publisher or subscriber is Agnocast-enabled.

  Parameters
  ----------
  topic_endpoints
      Result of ``_fetch_all_topic_info()``.  If ``None``, all edges
      that don't already have ``is_agnocast`` are set to ``False``.
  """
  if topic_endpoints is None:
    for edge in graph.edges:
      graph.edges[edge].setdefault('is_agnocast', False)
    return graph

  # Build lookup: topic → set of quoted Agnocast pub/sub node names
  topic_agnocast_pubs: dict[str, set[str]] = {}
  topic_agnocast_subs: dict[str, set[str]] = {}

  for topic, endpoints in topic_endpoints.items():
    pub_nodes = set()
    for ep in endpoints.agnocast_pubs:
      if not ep.is_bridge:
        pub_nodes.add(_quote_name(ep.node_name))
    topic_agnocast_pubs[topic] = pub_nodes

    sub_nodes = set()
    for ep in endpoints.agnocast_subs:
      if not ep.is_bridge:
        sub_nodes.add(_quote_name(ep.node_name))
    topic_agnocast_subs[topic] = sub_nodes

  for edge in graph.edges:
    # Skip edges already marked (e.g. newly added ③ edges)
    if 'is_agnocast' in graph.edges[edge]:
      continue

    src, dst, _ = edge
    label = graph.edges[edge].get('label', '').strip('"')

    if not label:
      graph.edges[edge]['is_agnocast'] = False
      continue

    is_agnocast_pub = src in topic_agnocast_pubs.get(label, set())
    is_agnocast_sub = dst in topic_agnocast_subs.get(label, set())
    graph.edges[edge]['is_agnocast'] = is_agnocast_pub or is_agnocast_sub

  return graph


# ---------------------------------------------------------------------------
# Graph modification: mark node attributes
# ---------------------------------------------------------------------------

def _mark_agnocast_nodes(graph: nx.MultiDiGraph,
             agnocast_only_nodes: set[str] | None
             ) -> nx.MultiDiGraph:
  """Set ``has_agnocast`` and ``agnocast_node_type`` on every node.

  ``has_agnocast`` is derived from edges: True if the node has at
  least one ``is_agnocast=True`` edge.

  ``agnocast_node_type`` is set to:
    - ``'agnocast_node'`` for ③ nodes
    - ``'rclcpp_with_agnocast'`` for ② nodes
    - ``'rclcpp_only'`` for ① nodes
  """
  # Collect nodes that touch an agnocast edge
  nodes_with_agnocast: set[str] = set()
  for edge in graph.edges:
    if graph.edges[edge].get('is_agnocast', False):
      src, dst, _ = edge
      nodes_with_agnocast.add(src)
      nodes_with_agnocast.add(dst)

  for node_name in graph.nodes:
    has_agnocast = node_name in nodes_with_agnocast
    graph.nodes[node_name]['has_agnocast'] = has_agnocast

  # Node type classification
  if agnocast_only_nodes is not None:
    quoted_agnocast_nodes = {_quote_name(n) for n in agnocast_only_nodes}
    for node_name in graph.nodes:
      if node_name in quoted_agnocast_nodes:
        graph.nodes[node_name]['agnocast_node_type'] = 'agnocast_node'
      elif graph.nodes[node_name].get('has_agnocast', False):
        graph.nodes[node_name]['agnocast_node_type'] = 'rclcpp_with_agnocast'
      else:
        graph.nodes[node_name]['agnocast_node_type'] = 'rclcpp_only'

  return graph


# ---------------------------------------------------------------------------
# Graph modification: bridge nodes
# ---------------------------------------------------------------------------

def _process_bridge_nodes(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
  """Detect bridge nodes and synthesize direct edges.

  Bridge nodes are identified by the ``agnocast_bridge_node_`` name prefix.
  For each bridge node, upstream and downstream edges are collected and
  a synthesized direct edge (``is_bridged=True``) is added to allow
  Show Bridge OFF display.

  This is the same logic as Phase 1's ``caret_extend_agnocast.py``.
  """
  bridge_nodes: set[str] = set()
  for node_name in graph.nodes:
    bare = node_name.strip('"')
    basename = bare.rsplit('/', 1)[-1] if '/' in bare else bare
    if basename.startswith(BRIDGE_NODE_PREFIX):
      graph.nodes[node_name]['is_bridge_node'] = True
      bridge_nodes.add(node_name)
    else:
      graph.nodes[node_name].setdefault('is_bridge_node', False)

  if not bridge_nodes:
    for edge in graph.edges:
      graph.edges[edge].setdefault('is_bridge_edge', False)
    return graph

  # Collect upstream/downstream per bridge node
  edges_to_add: list[dict] = []
  for bridge_node in bridge_nodes:
    upstream: list[tuple[str, str]] = []   # (src_node, label)
    downstream: list[tuple[str, str]] = []  # (dst_node, label)

    for edge in graph.edges:
      src, dst, _ = edge
      if dst == bridge_node:
        upstream.append((src, graph.edges[edge].get('label', '')))
        graph.edges[edge]['is_bridge_edge'] = True
      elif src == bridge_node:
        downstream.append((dst, graph.edges[edge].get('label', '')))
        graph.edges[edge]['is_bridge_edge'] = True

    # Synthesize direct edges: upstream × downstream
    for src, label_src in upstream:
      for dst, label_dst in downstream:
        edges_to_add.append({
          'src': src,
          'dst': dst,
          'label_src': label_src,
          'label_dst': label_dst,
        })

  for e in edges_to_add:
    graph.add_edge(
      e['src'], e['dst'],
      label=e['label_dst'],
      label_src=e['label_src'],
      label_dst=e['label_dst'],
      is_agnocast=True,
      is_bridged=True,
      is_bridge_edge=False,
    )

  # Default for edges not yet marked
  for edge in graph.edges:
    graph.edges[edge].setdefault('is_bridge_edge', False)

  return graph


# ---------------------------------------------------------------------------
# Default attributes (CLI failure fallback)
# ---------------------------------------------------------------------------

def _set_default_attributes(graph: nx.MultiDiGraph) -> None:
  """Set safe defaults when CLI is completely unavailable."""
  for node_name in graph.nodes:
    graph.nodes[node_name]['has_agnocast'] = False
    graph.nodes[node_name]['is_bridge_node'] = False
  for edge in graph.edges:
    graph.edges[edge]['is_agnocast'] = False
    graph.edges[edge]['is_bridge_edge'] = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extend_agnocast_runtime(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
  """Extend graph with Agnocast attributes from runtime CLI.

  Processing order:
    1. ``ros2 node list_agnocast``  — identify ③ nodes
    2. ``ros2 node info_agnocast``  — get ③ nodes' pub/sub topics  (×M)
    3. ``ros2 topic info_agnocast --all -v`` — all endpoint information
    4. Add ③ nodes and their edges to the graph
    5. Mark ``is_agnocast`` on existing edges
    6. Mark ``has_agnocast`` / ``agnocast_node_type`` on nodes
    7. Detect bridge nodes and synthesize direct edges

  On CLI failure, returns the graph with safe default attributes
  (graceful degradation).

  Parameters
  ----------
  graph : nx.MultiDiGraph
      Graph built by ``dot2networkx()``, before ``load_graph_postprocess()``.

  Returns
  -------
  graph : nx.MultiDiGraph
      Same graph with Agnocast attributes added.
  """

  # --- Step 1: ros2 node list_agnocast ---
  node_list_result = _fetch_node_list()
  if node_list_result is None:
    logger.info('Agnocast node list unavailable. Agnocast features disabled.')
    _set_default_attributes(graph)
    return graph

  agnocast_only_nodes, _all_nodes = node_list_result
  logger.info('Agnocast-only (③) nodes: %d', len(agnocast_only_nodes))

  # --- Step 2: ros2 node info_agnocast × M (③ nodes only) ---
  node_topics: dict[str, tuple[set[str], set[str]]] = {}
  for node_name in agnocast_only_nodes:
    basename = _extract_node_basename(node_name)
    if basename.startswith(BRIDGE_NODE_PREFIX):
      continue
    result = _fetch_node_info(node_name)
    if result is not None:
      node_topics[node_name] = result
      logger.debug('③ node info: %s  pub=%s sub=%s',
             node_name, result[0], result[1])

  # --- Step 3: ros2 topic info_agnocast --all -v ---
  topic_endpoints = _fetch_all_topic_info()
  if topic_endpoints is not None:
    logger.info('Topic endpoint info retrieved for %d topics',
          len(topic_endpoints))

  # --- Step 4: Add ③ nodes ---
  graph = _add_agnocast_nodes(graph, agnocast_only_nodes, node_topics,
                topic_endpoints)

  # --- Step 5: Mark is_agnocast on edges ---
  graph = _mark_agnocast_edges(graph, topic_endpoints)

  # --- Step 6: Mark node attributes ---
  graph = _mark_agnocast_nodes(graph, agnocast_only_nodes)

  # --- Step 7: Bridge processing ---
  graph = _process_bridge_nodes(graph)

  return graph
