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
from terminatorlib.util import dbg, err
from terminatorlib.terminator import Terminator

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
    mqtt_connections = None
    vte_version = Vte.get_minor_version()

    def __init__(self):
        plugin.MenuItem.__init__(self)
        if not self.mqtt_connections:
            self.mqtt_connections = {}
        
        # Отложенное подключение к терминалам, чтобы избежать ошибок инициализации
        GLib.idle_add(self.connect_to_terminals)
    
    def connect_to_terminals(self):
        """Подключение к существующим терминалам после инициализации"""
        try:
            terminator = Terminator()
            for terminal in terminator.terminals:
                terminal.connect('close-term', self.on_terminal_closed)
        except Exception as e:
            err(f"Couldn't connect to terminals: {str(e)}")
        return False  # Только одно выполнение

    def callback(self, menuitems, menu, terminal):
        """ Add menu items to the terminal menu """
        if not MQTT_AVAILABLE:
            item = Gtk.MenuItem.new_with_mnemonic(_('MQTT Not Available (install python3-paho-mqtt)'))
            item.set_sensitive(False)
            menuitems.append(item)
            return

        vte_terminal = terminal.get_vte()
        
        # Add menu items for MQTT connection management
        if vte_terminal not in self.mqtt_connections:
            item = Gtk.MenuItem.new_with_mnemonic(_('Configure MQTT Connection'))
            item.connect("activate", self.configure_mqtt, terminal)
        else:
            item = Gtk.MenuItem.new_with_mnemonic(_('Disconnect MQTT'))
            item.connect("activate", self.stop_mqtt, terminal)
            item.set_has_tooltip(True)
            conn_info = self.mqtt_connections[vte_terminal]
            tooltip = f"Connected to {conn_info['broker']}:{conn_info['port']}\n"
            tooltip += f"Publishing to: {conn_info['pub_topic']}\n"
            tooltip += f"Subscribed to: {conn_info['sub_topic']}"
            item.set_tooltip_text(tooltip)
        
        menuitems.append(item)
        
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
            if not self.mqtt_connections[terminal]["mqtt_client"].is_connected():
                return
                
            last_saved_col = self.mqtt_connections[terminal]["col"]
            last_saved_row = self.mqtt_connections[terminal]["row"]
            (col, row) = terminal.get_cursor_position()
            
            # Only send data when there's enough new content
            if row - last_saved_row < 1:  # Changed for more frequent updates
                return
                
            content = self.extract_content(terminal, last_saved_row, last_saved_col, row, col)
            if content:
                # Don't send the last char (usually '\n')
                self.mqtt_connections[terminal]["mqtt_client"].publish(
                    self.mqtt_connections[terminal]["pub_topic"],
                    content[:-1]
                )
                
            self.mqtt_connections[terminal]["col"] = col
            self.mqtt_connections[terminal]["row"] = row
        except Exception as e:
            sys.stderr.write(f"MQTT Publisher error: {str(e)}\n")

    def configure_mqtt(self, _widget, terminal):
        """ Start MQTT connection setup """
        # Подключаем обработчик закрытия для нового терминала
        terminal.connect('close-term', self.on_terminal_closed)
        
        dialog = MQTTConfigDialog(_widget.get_toplevel(), _("MQTT Configuration"))
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            try:
                broker = dialog.get_broker()
                port = dialog.get_port()
                pub_topic = dialog.get_pub_topic()
                sub_topic = dialog.get_sub_topic()
                username = dialog.get_username()
                password = dialog.get_password()
                
                # Create MQTT client
                client_id = f"terminator-{os.getpid()}-{terminal.uuid}"
                mqtt_client = mqtt.Client(client_id=client_id, userdata={'terminal': terminal})
                
                # Set credentials if provided
                if username:
                    mqtt_client.username_pw_set(username, password)
                
                # Set up callbacks
                mqtt_client.on_message = self.on_mqtt_message
                
                # Connect to broker
                mqtt_client.connect(broker, port)
                
                # Subscribe to topic for receiving commands
                mqtt_client.subscribe(sub_topic)
                mqtt_client.loop_start()
                
                # Store connection info
                vte_terminal = terminal.get_vte()
                (col, row) = vte_terminal.get_cursor_position()
                
                self.mqtt_connections[vte_terminal] = {
                    "mqtt_client": mqtt_client,
                    "broker": broker,
                    "port": port,
                    "pub_topic": pub_topic,
                    "sub_topic": sub_topic,
                    "col": col,
                    "row": row,
                    "handler_id": 0
                }
                
                # Connect the contents-changed signal for publishing
                handler_id = vte_terminal.connect('contents-changed', 
                                               lambda vte: self.mqtt_publish(vte))
                self.mqtt_connections[vte_terminal]["handler_id"] = handler_id
                
            except Exception as e:
                error = Gtk.MessageDialog(None, Gtk.DialogFlags.MODAL, 
                                         Gtk.MessageType.ERROR,
                                         Gtk.ButtonsType.OK, 
                                         f"Error connecting to MQTT broker: {str(e)}")
                error.set_transient_for(dialog)
                error.run()
                error.destroy()
                
        dialog.destroy()

    def stop_mqtt(self, _widget, terminal):
        """ Stop MQTT connection """
        vte_terminal = terminal.get_vte()
        if vte_terminal in self.mqtt_connections:
            # Disconnect signal
            vte_terminal.disconnect(self.mqtt_connections[vte_terminal]["handler_id"])
            
            # Stop MQTT client
            self.mqtt_connections[vte_terminal]["mqtt_client"].loop_stop()
            self.mqtt_connections[vte_terminal]["mqtt_client"].disconnect()
            
            # Remove from connections dict
            del self.mqtt_connections[vte_terminal]

    def on_mqtt_message(self, client, userdata, msg):
        """ Callback for received MQTT messages """
        if not userdata or 'terminal' not in userdata:
            return
            
        terminal = userdata['terminal']
        
        # Проверяем, существует ли еще терминал в списке терминалов Terminator
        if terminal not in Terminator().terminals:
            # Терминал был закрыт, нужно отключить MQTT слушателя
            try:
                client.disconnect()
                client.loop_stop()
                dbg('MQTT client disconnected because terminal was closed')
            except Exception as e:
                sys.stderr.write(f"Error disconnecting MQTT client: {str(e)}\n")
            return
        
        # We need to schedule the feed in the main GTK thread
        def feed_to_terminal():
            try:
                if isinstance(msg.payload, bytes):
                    payload = msg.payload.decode('utf-8')
                else:
                    payload = str(msg.payload)
                    
                # Проверяем снова здесь, т.к. терминал мог быть закрыт между проверкой выше
                # и выполнением этого кода
                if terminal not in Terminator().terminals:
                    return False
                    
                # Совершенно удаляем любые завершающие переводы строки из входящего сообщения
                payload = payload.rstrip('\r\n')
                
                # А теперь добавляем ОДИН перевод строки для выполнения команды
                payload += '\n'
                
                # Дополнительная проверка перед использованием терминала
                vte_terminal = terminal.get_vte()
                if vte_terminal:
                    vte_terminal.feed_child(payload.encode())
                return False  # Don't repeat
            except Exception as e:
                sys.stderr.write(f"Error feeding MQTT message to terminal: {str(e)}\n")
                return False
                
        # Schedule the GUI update in the main thread
        GLib.idle_add(feed_to_terminal)

    def on_terminal_closed(self, terminal):
        """Обработчик закрытия терминала - отключаем связанные MQTT соединения"""
        try:
            vte_terminal = terminal.get_vte()
            if vte_terminal in self.mqtt_connections:
                dbg(f"Terminal closed, stopping MQTT connections for {terminal}")
                # Отключаем сигнал, если он еще существует
                try:
                    vte_terminal.disconnect(self.mqtt_connections[vte_terminal]["handler_id"])
                except:
                    pass  # Сигнал может быть уже отключен
                
                # Останавливаем MQTT клиент
                self.mqtt_connections[vte_terminal]["mqtt_client"].loop_stop()
                self.mqtt_connections[vte_terminal]["mqtt_client"].disconnect()
                
                # Удаляем из mqtt_connections
                del self.mqtt_connections[vte_terminal]
        except Exception as e:
            sys.stderr.write(f"Error cleaning up MQTT on terminal close: {str(e)}\n")
            

class MQTTConfigDialog(Gtk.Dialog):
    """ Dialog for configuring MQTT connection """
    
    def __init__(self, parent, title):
        buttons = (
            _("_Cancel"), Gtk.ResponseType.CANCEL,
            _("_Connect"), Gtk.ResponseType.OK
        )
        
        Gtk.Dialog.__init__(self, title=title, transient_for=parent, flags=0, buttons=buttons)
        self.set_default_size(500, 350)
        self.set_border_width(10)
        
        # Create grid for form elements
        grid = Gtk.Grid()
        grid.set_row_spacing(10)
        grid.set_column_spacing(10)
        grid.set_border_width(10)
        
        # Connection section
        connection_label = Gtk.Label(label="<b>MQTT Broker Connection</b>")
        connection_label.set_use_markup(True)
        connection_label.set_halign(Gtk.Align.START)
        
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
        
        # Topics section
        topics_label = Gtk.Label(label="<b>MQTT Topics</b>")
        topics_label.set_use_markup(True)
        topics_label.set_halign(Gtk.Align.START)
        
        # Publishing topic
        pub_topic_label = Gtk.Label(label="Publishing topic:")
        pub_topic_label.set_halign(Gtk.Align.END)
        self.pub_topic_entry = Gtk.Entry()
        self.pub_topic_entry.set_text("terminator/output")
        self.pub_topic_entry.set_hexpand(True)
        
        # Subscription topic
        sub_topic_label = Gtk.Label(label="Subscription topic:")
        sub_topic_label.set_halign(Gtk.Align.END)
        self.sub_topic_entry = Gtk.Entry()
        self.sub_topic_entry.set_text("terminator/input")
        self.sub_topic_entry.set_hexpand(True)
        
        # Authentication section
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
        
        # Help text
        help_label = Gtk.Label()
        help_text = "• Publishing topic receives output from the terminal\n"
        help_text += "• Subscription topic sends commands to the terminal\n"
        help_text += "• Use mosquitto_pub/mosquitto_sub to test the connection"
        help_label.set_text(help_text)
        help_label.set_halign(Gtk.Align.START)
        
        # Add widgets to grid (row, column, width, height)
        grid.attach(connection_label, 0, 0, 4, 1)
        
        grid.attach(broker_label, 0, 1, 1, 1)
        grid.attach(self.broker_entry, 1, 1, 1, 1)
        grid.attach(port_label, 2, 1, 1, 1)
        grid.attach(self.port_entry, 3, 1, 1, 1)
        
        grid.attach(topics_label, 0, 3, 4, 1)
        
        grid.attach(pub_topic_label, 0, 4, 1, 1)
        grid.attach(self.pub_topic_entry, 1, 4, 3, 1)
        
        grid.attach(sub_topic_label, 0, 5, 1, 1)
        grid.attach(self.sub_topic_entry, 1, 5, 3, 1)
        
        grid.attach(auth_label, 0, 7, 4, 1)
        
        grid.attach(username_label, 0, 8, 1, 1)
        grid.attach(self.username_entry, 1, 8, 3, 1)
        
        grid.attach(password_label, 0, 9, 1, 1)
        grid.attach(self.password_entry, 1, 9, 3, 1)
        
        grid.attach(help_label, 0, 11, 4, 1)
        
        # Add the grid to the dialog
        content_area = self.get_content_area()
        content_area.add(grid)
        
        self.show_all()
    
    def get_broker(self):
        return self.broker_entry.get_text()
    
    def get_port(self):
        return int(self.port_entry.get_value())
    
    def get_pub_topic(self):
        return self.pub_topic_entry.get_text()
    
    def get_sub_topic(self):
        return self.sub_topic_entry.get_text()
    
    def get_username(self):
        return self.username_entry.get_text()
    
    def get_password(self):
        return self.password_entry.get_text()