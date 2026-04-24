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
"""Class to display node graph"""
from __future__ import annotations
import networkx as nx
import dearpygui.dearpygui as dpg
from .logger_factory import LoggerFactory
from .graph_viewmodel import GraphViewModel

logger = LoggerFactory.create(__name__)


class GraphView:
  """Class to display node graph"""
  def __init__(
      self,
      app_setting: dict,
      group_setting: dict
      ):

    self.app_setting: dict = app_setting
    self.graph_viewmodel = GraphViewModel(app_setting, group_setting)
    self.font_size: int = 15
    self.font_list: dict[int, int] = {}
    self.dpg_window_id: int = -1
    self.dpg_id_editor: int = -1
    self.dpg_id_caret_path: int = -1
    self.dpg_id_mermaid_export_dialog: int = -1

    # Agnocast menu item IDs
    self.dpg_id_agnocast: int = -1
    self.dpg_id_bridge: int = -1

    # Agnocast list panel
    self.dpg_id_agnocast_panel: int = -1
    self.dpg_id_agnocast_panel_content: int = -1
    self._dpg_panel_selectable_ids: list[int] = []  # all selectables for single-select
    self._dpg_panel_bridge_label_ids: list[int] = []  # bridge section widgets to show/hide

    self.color_node_selected = [0, 0, 64]
    self.color_node_bar = [32, 32, 32]
    self.color_node_back = [64, 64, 64]
    if self.app_setting['bg_white']:
      self.color_node_selected = [val + 180 for val in self.color_node_selected]
      self.color_node_bar = [val + 180 for val in self.color_node_bar]
      self.color_node_back = [val + 180 for val in self.color_node_back]

  def start(self, graph_filename: str, display_cb_detail: bool, window_width: int = 1920, window_height: int = 1080):
    """ Start Dear PyGui context """
    dpg.create_context()
    dpg.create_viewport(
      title='Dear RosNodeViewer', width=window_width, height=window_height,)
    dpg.setup_dearpygui()

    if self.app_setting['bg_white']:
      self._apply_global_white_theme()

    self._make_font_table(self.app_setting['font'])
    with dpg.handler_registry():
      dpg.add_mouse_wheel_handler(callback=self._cb_wheel)
      dpg.add_key_press_handler(callback=self._cb_key_press)

    with dpg.window(
        pos=[0, 0],
        width=window_width, height=window_height,
        no_collapse=True, no_title_bar=True, no_move=True,
        no_resize=True, no_bring_to_front_on_focus=True) as self.dpg_window_id:

      self.add_menu_in_dpg()

    self._setup_mermaid_export_dialog()
    self._setup_agnocast_panel()  # must be after main window

    # Explicitly bind the global white theme to the main window so that the
    # menubar background is also covered (dpg.bind_theme() alone is not enough).
    if self.app_setting['bg_white'] and hasattr(self, '_global_white_theme_id'):
      dpg.bind_item_theme(self.dpg_window_id, self._global_white_theme_id)
    self.graph_viewmodel.load_graph(graph_filename)
    self.update_node_editor(self.app_setting['bg_white'], display_cb_detail)

    # Update node position and font according to the default graph size and font size
    self._cb_wheel(0, 0)
    self._cb_menu_font_size(None, self.font_size, None)

    dpg.set_viewport_resize_callback(self._cb_resize)
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.destroy_context()

  def update_node_editor(self, bg_white:bool=False, display_cb_detail: bool=False):
    """Update node editor"""
    if self.dpg_id_editor != -1:
      dpg.delete_item(self.dpg_id_editor)

    with dpg.window(tag=self.dpg_window_id):
      with dpg.node_editor(
          menubar=False, minimap=True,
          minimap_location=dpg.mvNodeMiniMap_Location_BottomLeft) as self.dpg_id_editor:
        self.add_node_in_dpg(display_cb_detail)
        self.add_link_in_dpg()

    if bg_white and hasattr(self, '_global_white_theme_id'):
      # Re-bind the global white theme to main window and editor.
      # This is needed because update_node_editor() recreates the editor item,
      # which loses any previously bound theme.
      dpg.bind_item_theme(self.dpg_window_id, self._global_white_theme_id)
      dpg.bind_item_theme(self.dpg_id_editor,  self._global_white_theme_id)

    self.graph_viewmodel.load_layout()

    # Add CARET path
    for path_name, _ in self.graph_viewmodel.graph_manager.caret_path_dict.items():
      dpg.add_menu_item(label=path_name, callback=self._cb_menu_caret_path,
                parent=self.dpg_id_caret_path)

    # Refresh agnocast panel if visible
    if self.dpg_id_agnocast_panel != -1 and dpg.is_item_visible(self.dpg_id_agnocast_panel):
      self._refresh_agnocast_panel()

  def add_menu_in_dpg(self):
    """ Add menu bar """
    with dpg.menu_bar():
      with dpg.menu(label="Layout"):
        dpg.add_menu_item(label="Reset", callback=self._cb_menu_layout_reset)
        dpg.add_menu_item(label="Save", callback=self._cb_menu_layout_save, shortcut='(s)')
        dpg.add_menu_item(label="Load", callback=self._cb_menu_layout_load, shortcut='(l)')

      dpg.add_menu_item(label="Copy", callback=self._cb_menu_copy, shortcut='(c)')

      with dpg.menu(label="Export"):
        dpg.add_menu_item(label="Export to Mermaid (HTML)", callback=self._cb_menu_export_mermaid_html, shortcut='(h)')

      with dpg.menu(label="Font"):
        dpg.add_slider_int(label="Font Size",
                   default_value=self.font_size, min_value=8, max_value=40,
                   callback=self._cb_menu_font_size)

      with dpg.menu(label="NodeName"):
        dpg.add_menu_item(label="Full", callback=self._cb_menu_nodename_full)
        dpg.add_menu_item(label="First + Last", callback=self._cb_menu_nodename_firstlast)
        dpg.add_menu_item(label="Last Only", callback=self._cb_menu_nodename_last)

      with dpg.menu(label="EdgeName"):
        dpg.add_menu_item(label="Full", callback=self._cb_menu_edgename_full)
        dpg.add_menu_item(label="First + Last", callback=self._cb_menu_edgename_firstlast)
        dpg.add_menu_item(label="Last Only", callback=self._cb_menu_edgename_last)

      with dpg.menu(label="CARET"):
        dpg.add_menu_item(label="Show Callback Group", callback=self._cb_menu_caret_callbackbroup)
        with dpg.menu(label="PATH") as self.dpg_id_caret_path:
          pass

      with dpg.menu(label="ROS"):
        dpg.add_menu_item(label="Load Current Gaph",
                  callback=self._cb_menu_graph_current)

      with dpg.menu(label="Agnocast"):
        self.dpg_id_agnocast = dpg.add_menu_item(
          label="Show Agnocast",
          callback=self._cb_menu_agnocast_toggle)
        self.dpg_id_bridge = dpg.add_menu_item(
          label="Show Bridge",
          callback=self._cb_menu_bridge_toggle)

  def add_node_in_dpg(self, display_cb_detail: bool):
    """ Add nodes and attributes """
    graph = self.graph_viewmodel.get_graph()
    for node_name in graph.nodes:
      # Calculate position in window
      pos = graph.nodes[node_name]['pos']
      pos = [
        pos[0] * self.graph_viewmodel.graph_size[0],
        pos[1] * self.graph_viewmodel.graph_size[1]]

      # Allocate node
      with dpg.node(label=node_name, pos=pos) as node_id:
        # Save node id
        self.graph_viewmodel.add_dpg_node_id(node_name, node_id)

        # Set color
        is_bridge = graph.nodes[node_name].get('is_bridge_node', False)
        with dpg.theme() as theme_id:
          with dpg.theme_component(dpg.mvNode):
            if is_bridge:
              title_color = self.graph_viewmodel.color_bridge_node
            elif 'color' in graph.nodes[node_name]:
              title_color = graph.nodes[node_name]['color']
            else:
              title_color = self.color_node_bar
            dpg.add_theme_color(
              dpg.mvNodeCol_TitleBar,
              title_color,
              category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(
              dpg.mvNodeCol_NodeBackgroundSelected,
              self.color_node_selected,
              category=dpg.mvThemeCat_Nodes)
            initial_bg = self.graph_viewmodel._resolve_node_color(node_name)
            theme_color = dpg.add_theme_color(
              dpg.mvNodeCol_NodeBackground,
              initial_bg,
              category=dpg.mvThemeCat_Nodes)
            # Set color value
            self.graph_viewmodel.add_dpg_node_color(node_name, theme_color)
            dpg.bind_item_theme(node_id, theme_id)

        # Set callback
        with dpg.item_handler_registry() as node_select_handler:
          dpg.add_item_clicked_handler(callback=self._cb_node_clicked)
          dpg.bind_item_handler_registry(node_id, node_select_handler)

        # Add text for node I/O(topics)
        self.add_node_attr_in_dpg(node_name, display_cb_detail)

        if is_bridge:
          self.graph_viewmodel.add_dpg_bridge_node_id(node_name, node_id)
          dpg.hide_item(node_id)

    self.graph_viewmodel.update_nodename(GraphViewModel.OmitType.LAST)
    self.graph_viewmodel.update_edgename(GraphViewModel.OmitType.LAST)

  def add_node_attr_in_dpg(self, node_name, display_cb_detail: bool):
    """ Add attributes in node """
    graph = self.graph_viewmodel.get_graph()
    edge_list_pub = []
    edge_list_sub = []
    for edge in graph.edges:
      if edge[0] == node_name:
        edge_data = graph.edges[edge]
        label = edge_data.get('label_src', edge_data.get('label', 'out'))
        if label in edge_list_pub:
          continue
        edge_list_pub.append(label)
      if edge[1] == node_name:
        edge_data = graph.edges[edge]
        label = edge_data.get('label_dst', edge_data.get('label', 'in'))
        if label in edge_list_sub:
          continue
        edge_list_sub.append(label)

    for edge in edge_list_sub:
      with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Input) as attr_id:
        text_id = dpg.add_text(default_value=edge)
        self.graph_viewmodel.add_dpg_nodeedge_idtext(node_name, edge, attr_id, text_id, port_type='in_')
    for edge in edge_list_pub:
      with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Output) as attr_id:
        text_id = dpg.add_text(default_value=edge)
        self.graph_viewmodel.add_dpg_nodeedge_idtext(node_name, edge, attr_id, text_id, port_type='out_')

    # Workaround for https://github.com/hoffstadt/DearPyGui/issues/2444
    # Otherwise, Nodes with the first attribute "empty" expand infinitely in width
    if not edge_list_pub and not edge_list_sub:
      with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Output):
        dpg.add_text("")

    # Add text for executor/callbackgroups
    self.add_node_callbackgroup_in_dpg(node_name, display_cb_detail)
    # Hide by default
    self.graph_viewmodel.display_callbackgroup(False)

  def add_node_callbackgroup_in_dpg(self, node_name, display_cb_detail: bool):
    """ Add callback group information """
    graph = self.graph_viewmodel.get_graph()
    if 'callback_group_list' in graph.nodes[node_name]:
      callback_group_list = graph.nodes[node_name]['callback_group_list']
      for callback_group in callback_group_list:
        executor_name = callback_group['executor_name']
        callback_group_name = callback_group['callback_group_name']
        # callback_group_type = callback_group['callback_group_type']
        callback_group_name = self.graph_viewmodel.omit_name(
          callback_group_name, GraphViewModel.OmitType.LAST)
        callback_detail_list = callback_group['callback_detail_list']
        color = callback_group['color']
        with dpg.node_attribute() as attr_id:
          dpg.add_text('=== Callback Group [' + executor_name + '] ===', color=color)
          if display_cb_detail:
            for callback_detail in callback_detail_list:
              # callback_name = callback_detail['callback_name']
              callback_type = callback_detail['callback_type']
              description = callback_detail['description']
              description = self.graph_viewmodel.omit_name(
                description, GraphViewModel.OmitType.LAST)
              dpg.add_text(default_value='cb_' + callback_type + ': ' + description,
                    color=color)
          self.graph_viewmodel.add_dpg_callbackgroup_id(
            callback_group['callback_group_name'], attr_id)

  def add_link_in_dpg(self):
    """ Add links between node I/O """
    graph = self.graph_viewmodel.get_graph()
    for edge in graph.edges:
      if 'label' in graph.edges[edge]:
        label = graph.edges[edge]['label']
        label_src = graph.edges[edge].get('label_src', label)
        label_dst = graph.edges[edge].get('label_dst', label)
        try:
          edge_id = dpg.add_node_link(
            self.graph_viewmodel.get_dpg_nodeedge_id(edge[0], label_src, port_type='out_'),
            self.graph_viewmodel.get_dpg_nodeedge_id(edge[1], label_dst, port_type='in_'),
            parent=self.dpg_id_editor)
        except KeyError:
          logger.debug('Edge attr not found: %s -> %s (%s)', edge[0], edge[1], label)
          continue
        self.graph_viewmodel.add_dpg_id_edge(label, edge_id)
      else:
        try:
          edge_id = dpg.add_node_link(
            self.graph_viewmodel.get_dpg_nodeedge_id(edge[0], 'out'),
            self.graph_viewmodel.get_dpg_nodeedge_id(edge[1], 'in'),
            parent=self.dpg_id_editor)
        except KeyError:
          logger.debug('Edge attr not found: %s -> %s', edge[0], edge[1])
          continue

      # Set color using the unified color resolver
      with dpg.theme() as theme_id:
        with dpg.theme_component(dpg.mvNodeLink):
          initial_color = self.graph_viewmodel._resolve_edge_color(edge)
          theme_color = dpg.add_theme_color(
            dpg.mvNodeCol_Link,
            initial_color,
            category=dpg.mvThemeCat_Nodes)
          self.graph_viewmodel.add_dpg_edge_color(edge, theme_color)
          dpg.bind_item_theme(edge_id, theme_id)

      # Register bridge edges and synthesized direct edges for visibility control
      is_bridge_edge = graph.edges[edge].get('is_bridge_edge', False)
      is_bridged = graph.edges[edge].get('is_bridged', False)

      if is_bridge_edge:
        self.graph_viewmodel.add_dpg_bridge_edge_id(edge, edge_id)
        dpg.hide_item(edge_id)  # hidden by default (Show Bridge OFF)
      elif is_bridged:
        self.graph_viewmodel.add_dpg_bridged_direct_edge_id(edge, edge_id)
        # shown by default (Show Bridge OFF = direct edges visible)

  def _cb_resize(self, sender, app_data):
    """
    callback function for window resized (Dear PyGui)
    change node editer size
    """
    window_width = app_data[2]
    window_height = app_data[3]
    dpg.set_item_width(self.dpg_window_id, window_width)
    dpg.set_item_height(self.dpg_window_id, window_height)

  def _cb_node_clicked(self, sender, app_data):
    """
    change connedted node color
    restore node color when re-clicked
    """
    node_id = app_data[1]
    self.graph_viewmodel.high_light_node(node_id)

  def _cb_wheel(self, sender, app_data):
    """
    callback function for mouse wheel in node editor(Dear PyGui)
    zoom in/out graph according to wheel direction
    """
    self.graph_viewmodel.zoom_inout(app_data > 0)

  def _cb_key_press(self, sender, app_data):
    """callback function for key press"""
    if app_data == dpg.mvKey_S:
      self._cb_menu_layout_save()
    elif app_data == dpg.mvKey_L:
      self._cb_menu_layout_load()
    elif app_data == dpg.mvKey_C:
      self._cb_menu_copy()
    elif app_data == dpg.mvKey_H:
      self._cb_menu_export_mermaid_html()

  def _cb_menu_layout_reset(self):
    """ Reset layout """
    self.graph_viewmodel.reset_layout()

  def _cb_menu_layout_save(self):
    """ Save current layout """
    self.graph_viewmodel.save_layout()

  def _cb_menu_layout_load(self):
    """ Load layout from file """
    self.graph_viewmodel.load_layout()

  def _cb_menu_copy(self):
    self.graph_viewmodel.copy_selected_node_name(self.dpg_id_editor)

  def _cb_menu_graph_current(self):
    """ Update graph using current ROS status """
    self.graph_viewmodel.load_running_graph()
    self.update_node_editor()

  def _cb_menu_font_size(self, sender, app_data, user_data):
    """ Change font size """
    self.font_size = app_data
    if self.font_size in self.font_list:
      self.graph_viewmodel.update_font(self.font_list[self.font_size])

  def _cb_menu_nodename_full(self):
    """ Display full name """
    self.graph_viewmodel.update_nodename(GraphViewModel.OmitType.FULL)

  def _cb_menu_nodename_firstlast(self):
    """ Display omitted name """
    self.graph_viewmodel.update_nodename(GraphViewModel.OmitType.FIRST_LAST)

  def _cb_menu_nodename_last(self):
    """ Display omitted name """
    self.graph_viewmodel.update_nodename(GraphViewModel.OmitType.LAST)

  def _cb_menu_edgename_full(self):
    """ Display full name """
    self.graph_viewmodel.update_edgename(GraphViewModel.OmitType.FULL)

  def _cb_menu_edgename_firstlast(self):
    """ Display omitted name """
    self.graph_viewmodel.update_edgename(GraphViewModel.OmitType.FIRST_LAST)

  def _cb_menu_edgename_last(self):
    """ Display omitted name """
    self.graph_viewmodel.update_edgename(GraphViewModel.OmitType.LAST)

  def _cb_menu_caret_callbackbroup(self, sender, app_data, user_data):
    """ Show callback group info """
    if dpg.get_item_label(sender) == 'Show Callback Group':
      self.graph_viewmodel.display_callbackgroup(True)
      dpg.set_item_label(sender, 'Hide Callback Group')
    else:
      self.graph_viewmodel.display_callbackgroup(False)
      dpg.set_item_label(sender, 'Show Callback Group')

  def _cb_menu_caret_path(self, sender, app_data, user_data):
    """ High light selected CARET path """
    path_name = dpg.get_item_label(sender)
    self.graph_viewmodel.high_light_caret_path(path_name)

  def _cb_menu_agnocast_toggle(self, sender, app_data, user_data):
    """Toggle Agnocast edge and node coloring together"""
    current = self.graph_viewmodel.agnocast_display['show_agnocast']
    self.graph_viewmodel.toggle_agnocast_display(not current)
    label = 'Hide Agnocast' if not current else 'Show Agnocast'
    dpg.set_item_label(sender, label)

    # Show/hide agnocast panel in sync
    if self.dpg_id_agnocast_panel != -1:
      if not current:
        self._refresh_agnocast_panel()
        dpg.show_item(self.dpg_id_agnocast_panel)
      else:
        dpg.hide_item(self.dpg_id_agnocast_panel)

  def _cb_menu_bridge_toggle(self, sender, app_data, user_data):
    """Toggle bridge node/edge visibility"""
    if not self.graph_viewmodel.has_bridge_nodes():
      logger.info('No bridge nodes in current graph')
      return
    current = self.graph_viewmodel.agnocast_display['show_bridge']
    self.graph_viewmodel.toggle_bridge_display(not current)
    label = 'Hide Bridge' if not current else 'Show Bridge'
    dpg.set_item_label(sender, label)

    # Refresh panel bridge section if visible
    if self.dpg_id_agnocast_panel != -1 and dpg.is_item_shown(self.dpg_id_agnocast_panel):
      self._refresh_agnocast_panel()

  def _apply_global_white_theme(self):
    """Apply a light global theme for bg_white mode (menubar, windows, text)."""
    with dpg.theme() as theme_id:
      with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_color(dpg.mvThemeCol_WindowBg,       (240, 240, 240))
        dpg.add_theme_color(dpg.mvThemeCol_ChildBg,        (225, 225, 225))
        dpg.add_theme_color(dpg.mvThemeCol_MenuBarBg,      (210, 210, 210))
        dpg.add_theme_color(dpg.mvThemeCol_PopupBg,        (240, 240, 240))
        dpg.add_theme_color(dpg.mvThemeCol_Text,           (20,  20,  20))
        dpg.add_theme_color(dpg.mvThemeCol_Header,         (180, 210, 230))
        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered,  (160, 195, 220))
        dpg.add_theme_color(dpg.mvThemeCol_HeaderActive,   (140, 180, 210))
        dpg.add_theme_color(dpg.mvThemeCol_FrameBg,        (210, 210, 210))
        dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (195, 195, 195))
        dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg,    (220, 220, 220))
        dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab,  (160, 160, 160))
        dpg.add_theme_color(dpg.mvThemeCol_Border,         (160, 160, 160))
        dpg.add_theme_color(dpg.mvThemeCol_Separator,      (160, 160, 160))
        dpg.add_theme_color(dpg.mvNodeCol_GridBackground,  (255, 255, 255), category=dpg.mvThemeCat_Nodes)
        dpg.add_theme_color(dpg.mvNodeCol_GridLine,        (220, 220, 220), category=dpg.mvThemeCat_Nodes)
    # Save theme ID so _setup_agnocast_panel() can bind it explicitly.
    # dpg.bind_theme() alone does not propagate to windows created after this call.
    self._global_white_theme_id = theme_id
    dpg.bind_theme(theme_id)

  def _setup_agnocast_panel(self):
    """Create the Agnocast list panel window (hidden by default)"""
    with dpg.window(
        label='Agnocast List',
        pos=[10, 30],
        width=260,
        height=500,
        show=False,
        no_close=True,
        no_collapse=True,
        no_move=True,
        no_title_bar=True,
        no_focus_on_appearing=True) as self.dpg_id_agnocast_panel:
      dpg.add_text('Agnocast Nodes', color=self.graph_viewmodel.color_agnocast_edge)
      dpg.add_separator()
      self._dpg_panel_nodes = dpg.add_child_window(height=140, border=True)
      dpg.add_separator()
      dpg.add_text('Agnocast Topics (Edges)', color=self.graph_viewmodel.color_agnocast_edge)
      dpg.add_separator()
      self._dpg_panel_edges = dpg.add_child_window(height=140, border=True)
      dpg.add_separator()
      self._dpg_panel_bridge_label_ids = [
        dpg.add_text('Bridge Nodes', color=self.graph_viewmodel.color_bridge_node),
        dpg.add_separator(),
        dpg.add_child_window(height=100, border=True),
      ]
      self._dpg_panel_bridges = self._dpg_panel_bridge_label_ids[2]

    # In bg_white mode, dpg.bind_theme() does not propagate to windows created
    # after the call, so we explicitly bind the global theme to this panel and
    # its child windows here.
    if self.app_setting['bg_white'] and hasattr(self, '_global_white_theme_id'):
      dpg.bind_item_theme(self.dpg_id_agnocast_panel, self._global_white_theme_id)
      dpg.bind_item_theme(self._dpg_panel_nodes,      self._global_white_theme_id)
      dpg.bind_item_theme(self._dpg_panel_edges,      self._global_white_theme_id)
      dpg.bind_item_theme(self._dpg_panel_bridges,    self._global_white_theme_id)

    logger.debug('agnocast_panel created id=%s nodes=%s edges=%s bridges=%s',
      self.dpg_id_agnocast_panel,
      self._dpg_panel_nodes,
      self._dpg_panel_edges,
      self._dpg_panel_bridges)

  def _refresh_agnocast_panel(self):
    """Rebuild the list panel content from the current graph"""
    graph = self.graph_viewmodel.get_graph()
    self._dpg_panel_selectable_ids.clear()

    # --- Agnocast nodes ---
    dpg.delete_item(self._dpg_panel_nodes, children_only=True)
    agnocast_nodes = [
      n for n in graph.nodes
      if graph.nodes[n].get('is_agnocast_node', False)
    ]
    if agnocast_nodes:
      for node_name in agnocast_nodes:
        short = '/' + node_name.strip('"').split('/')[-1]
        sel_id = dpg.add_selectable(
          label=short,
          parent=self._dpg_panel_nodes,
          callback=self._cb_panel_jump_to_node,
          user_data=node_name)
        self._dpg_panel_selectable_ids.append(sel_id)
    else:
      dpg.add_text('(none)', parent=self._dpg_panel_nodes, color=[128, 128, 128])

    # --- Agnocast edges (unique topic labels) ---
    dpg.delete_item(self._dpg_panel_edges, children_only=True)
    agnocast_topics = []
    agnocast_edge_map = {}
    for edge in graph.edges:
      edge_data = graph.edges[edge]
      if edge_data.get('is_agnocast', False):
        label = edge_data.get('label', str(edge))
        label = label.replace('_agnocast', '')
        if label not in agnocast_topics:
          agnocast_topics.append(label)
          agnocast_edge_map[label] = edge[0]
    if agnocast_topics:
      for topic in sorted(agnocast_topics):
        short = '/' + topic.strip('"').split('/')[-1]
        sel_id = dpg.add_selectable(
          label=short,
          parent=self._dpg_panel_edges,
          callback=self._cb_panel_jump_to_node,
          user_data=agnocast_edge_map[topic])
        self._dpg_panel_selectable_ids.append(sel_id)
    else:
      dpg.add_text('(none)', parent=self._dpg_panel_edges, color=[128, 128, 128])

    # --- Bridge nodes (show only when show_bridge is ON) ---
    show_bridge = self.graph_viewmodel.agnocast_display['show_bridge']
    for item_id in self._dpg_panel_bridge_label_ids:
      if show_bridge:
        dpg.show_item(item_id)
      else:
        dpg.hide_item(item_id)

    dpg.delete_item(self._dpg_panel_bridges, children_only=True)
    if show_bridge:
      bridge_nodes = [
        n for n in graph.nodes
        if graph.nodes[n].get('is_bridge_node', False)
      ]
      if bridge_nodes:
        for node_name in bridge_nodes:
          short = '/' + node_name.strip('"').split('/')[-1]
          sel_id = dpg.add_selectable(
            label=short,
            parent=self._dpg_panel_bridges,
            callback=self._cb_panel_jump_to_node,
            user_data=node_name)
          self._dpg_panel_selectable_ids.append(sel_id)
      else:
        dpg.add_text('(none)', parent=self._dpg_panel_bridges, color=[128, 128, 128])

  def _cb_panel_jump_to_node(self, sender, app_data, user_data):
    """Move target node to center. Deselect all other selectables (single-select)."""
    # Enforce single selection
    for sel_id in self._dpg_panel_selectable_ids:
      if sel_id != sender:
        dpg.set_value(sel_id, False)

    node_name = user_data
    target_id = self.graph_viewmodel.dpg_bind['node_id'].get(node_name)
    if target_id is None:
      return

    # Screen position of the target node
    target_screen = dpg.get_item_rect_min(target_id)

    # Screen center of the visible area (exclude panel on the left)
    window_w = dpg.get_item_width(self.dpg_window_id)
    window_h = dpg.get_item_height(self.dpg_window_id)
    panel_w = 260 + 10  # panel width + left margin
    center_screen_x = panel_w + (window_w - panel_w) // 2
    center_screen_y = window_h // 2

    # Delta in screen space = delta in canvas space (zoom is uniform scaling)
    dx = center_screen_x - target_screen[0]
    dy = center_screen_y - target_screen[1]

    for nid in self.graph_viewmodel.dpg_bind['node_id'].values():
      pos = dpg.get_item_pos(nid)
      dpg.set_item_pos(nid, [pos[0] + dx, pos[1] + dy])

  def _setup_mermaid_export_dialog(self):
    """ Setup folder selection dialog for Mermaid export """
    with dpg.file_dialog(
        directory_selector=True,
        show=False,
        callback=self._cb_mermaid_export_dialog,
        tag="mermaid_export_dialog",
        width=700,
        height=400) as self.dpg_id_mermaid_export_dialog:
      pass

  def _cb_mermaid_export_dialog(self, sender, app_data, user_data):
    """ Callback for folder selection dialog """
    if app_data and 'file_path_name' in app_data and app_data['file_path_name']:
      selected_path = app_data['file_path_name']
      # Ensure path ends with '/' for consistency
      if not selected_path.endswith('/'):
        selected_path += '/'
      html_path = self.graph_viewmodel.export_to_mermaid(selected_path)
      logger.info(f"Exported to Mermaid HTML: {html_path}")
    else:
      # User cancelled the dialog
      logger.info("Mermaid export cancelled by user")

  def _cb_menu_export_mermaid_html(self):
    """ Export graph to Mermaid HTML format """
    dpg.show_item(self.dpg_id_mermaid_export_dialog)

  def _make_font_table(self, font_path):
    """Make font table"""
    with dpg.font_registry():
      for i in range(8, 40):
        try:
          self.font_list[i] = dpg.add_font(font_path, i)
        except SystemError:
          logger.error('Failed to load font: %s', font_path)


if __name__ == '__main__':
  def local_main():
    """main function for this file"""
    graph = nx.MultiDiGraph()
    nx.add_path(graph, ['3', '5', '4', '1', '0', '2'])
    nx.add_path(graph, ['3', '0', '4', '2', '1', '5'])
    layout = nx.spring_layout(graph)
    for key, val in layout.items():
      graph.nodes[key]['pos'] = list(val)
      graph.nodes[key]['color'] = [128, 128, 128]
    app_setting = {
      "font": "/usr/share/fonts/truetype/ubuntu/Ubuntu-C.ttf"
    }
    GraphView(app_setting, graph)

  local_main()
