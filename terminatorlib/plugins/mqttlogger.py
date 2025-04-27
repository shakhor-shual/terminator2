# Plugin by GitHub Copilot, based on Logger plugin by Sinan Nalkaya <sardok@gmail.com>
# See LICENSE of Terminator package.

""" mqttlogger.py - Terminator Plugin to interact with MQTT broker.
    Can send terminal output to MQTT topics and receive messages from MQTT topics.
"""

import os
import sys
import threading
import time
from gi.repository import Gtk, Gdk, GLib, Vte
import terminatorlib.plugin as plugin
from terminatorlib.translation import _

# Import the MQTT client library
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

AVAILABLE = ['MQTTLogger']

class MQTTLogger(plugin.MenuItem):
    """ Add MQTT integration to the terminal menu """
    capabilities = ['terminal_menu']
    loggers = None
    receivers = None
    vte_version = Vte.get_minor_version()

    def __init__(self):
        plugin.MenuItem.__init__(self)
        if not self.loggers:
            self.loggers = {}
        if not self.receivers:
            self.receivers = {}

    def callback(self, menuitems, menu, terminal):
        """ Add menu items to the terminal menu """
        if not MQTT_AVAILABLE:
            item = Gtk.MenuItem.new_with_mnemonic(_('MQTT Not Available (install python3-paho-mqtt)'))
            item.set_sensitive(False)
            menuitems.append(item)
            return

        submenu = Gtk.Menu()
        
        vte_terminal = terminal.get_vte()
        
        # Add menu item for sending terminal output to MQTT
        if vte_terminal not in self.loggers:
            item = Gtk.MenuItem.new_with_mnemonic(_('Start MQTT Publisher'))
            item.connect("activate", self.start_mqtt_publisher, terminal)
        else:
            item = Gtk.MenuItem.new_with_mnemonic(_('Stop MQTT Publisher'))
            item.connect("activate", self.stop_mqtt_publisher, terminal)
            item.set_has_tooltip(True)
            item.set_tooltip_text(f"Publishing to {self.loggers[vte_terminal]['mqtt_topic']} on {self.loggers[vte_terminal]['broker']}")
        
        submenu.append(item)
        
        # Add separator
        separator = Gtk.SeparatorMenuItem()
        submenu.append(separator)
        
        # Add menu item for receiving MQTT messages
        if vte_terminal not in self.receivers:
            item = Gtk.MenuItem.new_with_mnemonic(_('Start MQTT Subscriber'))
            item.connect("activate", self.start_mqtt_subscriber, terminal)
        else:
            item = Gtk.MenuItem.new_with_mnemonic(_('Stop MQTT Subscriber'))
            item.connect("activate", self.stop_mqtt_subscriber, terminal)
            item.set_has_tooltip(True)
            item.set_tooltip_text(f"Subscribed to {self.receivers[vte_terminal]['mqtt_topic']} on {self.receivers[vte_terminal]['broker']}")
        
        submenu.append(item)
        
        # Create a main menu item to hold the submenu
        main_item = Gtk.MenuItem.new_with_mnemonic(_('_MQTT'))
        main_item.set_submenu(submenu)
        menuitems.append(main_item)
        
    def extract_content(self, terminal, row_start, col_start, row_end, col_end):
        """ Extract text content from terminal """
        if self.vte_version < 72:
            content = terminal.get_text_range(row_start, col_start, row_end, col_end,
                                          lambda *a: True)
        else:
            content = terminal.get_text_range_format(Vte.Format.TEXT, row_start, col_start, row_end, col_end)
        return content[0] if content else ""

    def mqtt_publish(self, terminal):
        """ MQTT publish callback when terminal content changes """
        try:
            # Only continue if we're connected
            if not self.loggers[terminal]["mqtt_client"].is_connected():
                return
                
            last_saved_col = self.loggers[terminal]["col"]
            last_saved_row = self.loggers[terminal]["row"]
            (col, row) = terminal.get_cursor_position()
            
            # Only send data when there's enough new content
            if row - last_saved_row < 1:  # Changed from terminal.get_row_count() for more frequent updates
                return
                
            content = self.extract_content(terminal, last_saved_row, last_saved_col, row, col)
            if content:
                # Don't send the last char (usually '\n')
                self.loggers[terminal]["mqtt_client"].publish(
                    self.loggers[terminal]["mqtt_topic"],
                    content[:-1]
                )
                
            self.loggers[terminal]["col"] = col
            self.loggers[terminal]["row"] = row
        except Exception as e:
            sys.stderr.write(f"MQTT Publisher error: {str(e)}\n")

    def start_mqtt_publisher(self, _widget, terminal):
        """ Start publishing terminal content to MQTT """
        dialog = MQTTConfigDialog(_widget.get_toplevel(), _("MQTT Publisher Configuration"), True)
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            try:
                broker = dialog.get_broker()
                port = dialog.get_port()
                topic = dialog.get_topic()
                username = dialog.get_username()
                password = dialog.get_password()
                
                # Create MQTT client
                client_id = f"terminator-{os.getpid()}-publisher"
                mqtt_client = mqtt.Client(client_id=client_id)
                
                # Set credentials if provided
                if username:
                    mqtt_client.username_pw_set(username, password)
                
                # Connect to broker
                mqtt_client.connect(broker, port)
                mqtt_client.loop_start()
                
                # Store connection info
                vte_terminal = terminal.get_vte()
                (col, row) = vte_terminal.get_cursor_position()
                
                self.loggers[vte_terminal] = {
                    "mqtt_client": mqtt_client,
                    "broker": broker,
                    "port": port,
                    "mqtt_topic": topic,
                    "col": col,
                    "row": row,
                    "handler_id": 0
                }
                
                # Connect the contents-changed signal
                handler_id = vte_terminal.connect('contents-changed', 
                                                lambda vte: self.mqtt_publish(vte))
                self.loggers[vte_terminal]["handler_id"] = handler_id
                
            except Exception as e:
                error = Gtk.MessageDialog(None, Gtk.DialogFlags.MODAL, 
                                         Gtk.MessageType.ERROR,
                                         Gtk.ButtonsType.OK, 
                                         f"Error connecting to MQTT broker: {str(e)}")
                error.set_transient_for(dialog)
                error.run()
                error.destroy()
                
        dialog.destroy()

    def stop_mqtt_publisher(self, _widget, terminal):
        """ Stop publishing terminal content to MQTT """
        vte_terminal = terminal.get_vte()
        if vte_terminal in self.loggers:
            # Disconnect signal
            vte_terminal.disconnect(self.loggers[vte_terminal]["handler_id"])
            
            # Stop MQTT client
            self.loggers[vte_terminal]["mqtt_client"].loop_stop()
            self.loggers[vte_terminal]["mqtt_client"].disconnect()
            
            # Remove from loggers dict
            del self.loggers[vte_terminal]

    def on_mqtt_message(self, client, userdata, msg):
        """ Callback for received MQTT messages """
        if not userdata or 'terminal' not in userdata:
            return
            
        terminal = userdata['terminal']
        
        # We need to schedule the feed in the main GTK thread
        def feed_to_terminal():
            try:
                if isinstance(msg.payload, bytes):
                    payload = msg.payload.decode('utf-8')
                else:
                    payload = str(msg.payload)
                    
                # Не добавляем лишний перевод строки, если только явно не запрошено
                # Оставляем команду как есть, чтобы не было двойных Enter
                # Проверяем, заканчивается ли сообщение переводом строки
                if not payload.endswith('\r\n') and not payload.endswith('\n'):
                    # Только если нет перевода строки, добавляем его
                    payload += '\r\n'
                
                # Используем feed_child на объекте VTE терминала для эмуляции ввода клавиатуры
                vte_terminal = terminal.get_vte()
                vte_terminal.feed_child(payload.encode())
                return False  # Don't repeat
            except Exception as e:
                sys.stderr.write(f"Error feeding MQTT message to terminal: {str(e)}\n")
                return False
                
        # Schedule the GUI update in the main thread
        GLib.idle_add(feed_to_terminal)

    def start_mqtt_subscriber(self, _widget, terminal):
        """ Start subscribing to MQTT topic """
        dialog = MQTTConfigDialog(_widget.get_toplevel(), _("MQTT Subscriber Configuration"), False)
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            try:
                broker = dialog.get_broker()
                port = dialog.get_port()
                topic = dialog.get_topic()
                username = dialog.get_username()
                password = dialog.get_password()
                
                # Create MQTT client
                client_id = f"terminator-{os.getpid()}-subscriber"
                mqtt_client = mqtt.Client(client_id=client_id, userdata={'terminal': terminal})
                
                # Set credentials if provided
                if username:
                    mqtt_client.username_pw_set(username, password)
                
                # Set up callbacks
                mqtt_client.on_message = self.on_mqtt_message
                
                # Connect to broker
                mqtt_client.connect(broker, port)
                
                # Subscribe to topic
                mqtt_client.subscribe(topic)
                mqtt_client.loop_start()
                
                vte_terminal = terminal.get_vte()
                self.receivers[vte_terminal] = {
                    "mqtt_client": mqtt_client,
                    "broker": broker,
                    "port": port,
                    "mqtt_topic": topic
                }
                
            except Exception as e:
                error = Gtk.MessageDialog(None, Gtk.DialogFlags.MODAL, 
                                         Gtk.MessageType.ERROR,
                                         Gtk.ButtonsType.OK, 
                                         f"Error connecting to MQTT broker: {str(e)}")
                error.set_transient_for(dialog)
                error.run()
                error.destroy()
                
        dialog.destroy()

    def stop_mqtt_subscriber(self, _widget, terminal):
        """ Stop subscribing to MQTT topic """
        vte_terminal = terminal.get_vte()
        if vte_terminal in self.receivers:
            # Stop MQTT client
            self.receivers[vte_terminal]["mqtt_client"].loop_stop()
            self.receivers[vte_terminal]["mqtt_client"].disconnect()
            
            # Remove from receivers dict
            del self.receivers[vte_terminal]


class MQTTConfigDialog(Gtk.Dialog):
    """ Dialog for configuring MQTT connection """
    
    def __init__(self, parent, title, is_publisher=True):
        buttons = (
            _("_Cancel"), Gtk.ResponseType.CANCEL,
            _("_Connect"), Gtk.ResponseType.OK
        )
        
        Gtk.Dialog.__init__(self, title=title, transient_for=parent, flags=0, buttons=buttons)
        self.set_default_size(400, 250)
        self.set_border_width(10)
        
        # Create grid for form elements
        grid = Gtk.Grid()
        grid.set_row_spacing(10)
        grid.set_column_spacing(10)
        grid.set_border_width(10)
        
        # Broker and port
        broker_label = Gtk.Label(label="Broker:")
        broker_label.set_halign(Gtk.Align.END)
        self.broker_entry = Gtk.Entry()
        self.broker_entry.set_text("localhost")
        self.broker_entry.set_hexpand(True)
        
        port_label = Gtk.Label(label="Port:")
        port_label.set_halign(Gtk.Align.END)
        self.port_entry = Gtk.SpinButton.new_with_range(1, 65535, 1)
        self.port_entry.set_value(1883)
        
        # Topic
        topic_label = Gtk.Label(label="Topic:")
        topic_label.set_halign(Gtk.Align.END)
        self.topic_entry = Gtk.Entry()
        if is_publisher:
            self.topic_entry.set_text("terminator/output")
        else:
            self.topic_entry.set_text("terminator/input")
        self.topic_entry.set_hexpand(True)
        
        # Authentication
        auth_label = Gtk.Label(label="<b>Authentication (optional)</b>")
        auth_label.set_use_markup(True)
        auth_label.set_halign(Gtk.Align.START)
        
        username_label = Gtk.Label(label="Username:")
        username_label.set_halign(Gtk.Align.END)
        self.username_entry = Gtk.Entry()
        
        password_label = Gtk.Label(label="Password:")
        password_label.set_halign(Gtk.Align.END)
        self.password_entry = Gtk.Entry()
        self.password_entry.set_visibility(False)
        self.password_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        
        # Add widgets to grid
        grid.attach(broker_label, 0, 0, 1, 1)
        grid.attach(self.broker_entry, 1, 0, 1, 1)
        grid.attach(port_label, 2, 0, 1, 1)
        grid.attach(self.port_entry, 3, 0, 1, 1)
        
        grid.attach(topic_label, 0, 1, 1, 1)
        grid.attach(self.topic_entry, 1, 1, 3, 1)
        
        grid.attach(auth_label, 0, 3, 4, 1)
        
        grid.attach(username_label, 0, 4, 1, 1)
        grid.attach(self.username_entry, 1, 4, 3, 1)
        
        grid.attach(password_label, 0, 5, 1, 1)
        grid.attach(self.password_entry, 1, 5, 3, 1)
        
        # Add the grid to the dialog
        content_area = self.get_content_area()
        content_area.add(grid)
        
        self.show_all()
    
    def get_broker(self):
        return self.broker_entry.get_text()
    
    def get_port(self):
        return int(self.port_entry.get_value())
    
    def get_topic(self):
        return self.topic_entry.get_text()
    
    def get_username(self):
        return self.username_entry.get_text()
    
    def get_password(self):
        return self.password_entry.get_text()