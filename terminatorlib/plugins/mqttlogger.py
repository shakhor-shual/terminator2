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

class MQTTLogger(plugin.TitlebarButton):
    """ Add MQTT integration to the terminal titlebar """
    capabilities = ['titlebar_button']
    mqtt_connections = None
    vte_version = Vte.get_minor_version()
    
    # Словарь для хранения MQTT-соединений по UUID терминала, а не по объекту VTE
    terminal_uuid_connections = None
    
    # Словарь для хранения кнопок, связанных с терминалами
    terminal_buttons = None

    def __init__(self):
        plugin.TitlebarButton.__init__(self)
        
        if not self.mqtt_connections:
            self.mqtt_connections = {}
        if not self.terminal_uuid_connections:
            self.terminal_uuid_connections = {}
        if not self.terminal_buttons:
            self.terminal_buttons = {}
        
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
    
    def get_button(self, terminal):
        """Создает и возвращает кнопку для панели заголовка терминала"""
        button = Gtk.Button()
        image = Gtk.Image()
        
        # Проверяем наличие UUID у терминала
        # Если uuid еще не инициализирован, создаем кнопку в отключенном состоянии
        terminal_uuid = None
        try:
            if hasattr(terminal, 'uuid') and terminal.uuid:
                terminal_uuid = terminal.uuid.urn
        except:
            pass
        
        connected = False
        if terminal_uuid:
            connected = self.is_terminal_connected(terminal_uuid)
        
        # Устанавливаем начальное состояние кнопки
        if not MQTT_AVAILABLE:
            image.set_from_icon_name('dialog-error', Gtk.IconSize.MENU)
            button.set_tooltip_text(_("MQTT Not Available (install python3-paho-mqtt)"))
            button.set_sensitive(False)
        elif connected:
            # Активное соединение
            image.set_from_icon_name('network-transmit-receive', Gtk.IconSize.MENU)
            conn_info = self.get_connection_info(terminal_uuid)
            if conn_info:
                button.set_tooltip_text(_(f"MQTT Connected: {conn_info['broker']}:{conn_info['port']}"))
        else:
            # Нет соединения
            image.set_from_icon_name('network-offline', Gtk.IconSize.MENU)
            button.set_tooltip_text(_("MQTT: Not Connected"))
        
        button.set_image(image)
        button.set_relief(Gtk.ReliefStyle.NONE)
        
        # Привязываем событие клика только если terminal.uuid инициализирован
        if terminal_uuid:
            button.connect('clicked', self.on_titlebar_button_clicked, terminal)
            # Сохраняем ссылку на кнопку для будущего обновления
            self.terminal_buttons[terminal_uuid] = button
        else:
            # Если uuid не инициализирован, подключаем обработчик для последующей инициализации
            def delayed_connect_handler(widget, event):
                # Проверяем, инициализирован ли uuid терминала
                if hasattr(terminal, 'uuid') and terminal.uuid:
                    terminal_uuid = terminal.uuid.urn
                    # Отключаем временный обработчик
                    button.disconnect_by_func(delayed_connect_handler)
                    # Подключаем настоящий обработчик
                    button.connect('clicked', self.on_titlebar_button_clicked, terminal)
                    # Сохраняем ссылку на кнопку
                    self.terminal_buttons[terminal_uuid] = button
                    # Обновляем состояние кнопки
                    self.update_button_state(terminal_uuid, False)
                    return False
                return True
            
            # Подключаем временный обработчик
            button.connect('button-press-event', delayed_connect_handler)
        
        return button
    
    def on_titlebar_button_clicked(self, widget, terminal):
        """Обработчик нажатия на кнопку MQTT в заголовке"""
        terminal_uuid = terminal.uuid.urn
        is_connected = self.is_terminal_connected(terminal_uuid)
        
        if is_connected:
            # Если соединение уже установлено, показываем диалог управления
            self.show_mqtt_status_dialog(widget.get_toplevel(), terminal)
        else:
            # Если соединения нет, запускаем настройку нового соединения
            self.configure_mqtt(widget, terminal)
        
    def is_terminal_connected(self, terminal_uuid):
        """Проверяет наличие активного MQTT-соединения для данного терминала"""
        # Прямая проверка наличия соединения по UUID
        return terminal_uuid in self.terminal_uuid_connections
    
    def get_connection_info(self, terminal_uuid):
        """Получает информацию о соединении для данного терминала по UUID"""
        if terminal_uuid in self.terminal_uuid_connections:
            return self.terminal_uuid_connections[terminal_uuid]
        return None
    
    def update_terminal_connections(self):
        """Обновляет информацию о состоянии подключения для терминалов"""
        try:
            # Проверяем все активные соединения
            for term_uuid in list(self.terminal_uuid_connections.keys()):
                # Проверяем, существует ли еще этот терминал
                terminal_exists = False
                for term in Terminator().terminals:
                    if term.uuid.urn == term_uuid:
                        terminal_exists = True
                        
                        # Терминал найден, проверим, что VTE правильно подключен
                        vte_terminal = term.get_vte()
                        if vte_terminal not in self.mqtt_connections:
                            # VTE изменился, обновим обработчики сигналов
                            handler_id = vte_terminal.connect('contents-changed', 
                                                         lambda vte: self.mqtt_publish(vte))
                            self.mqtt_connections[vte_terminal] = {
                                "handler_id": handler_id,
                                "terminal_uuid": term_uuid
                            }
                        break
                
                if not terminal_exists:
                    # Терминал был закрыт, отключаем MQTT и удаляем информацию
                    conn_info = self.terminal_uuid_connections[term_uuid]
                    if conn_info["mqtt_client"].is_connected():
                        conn_info["mqtt_client"].loop_stop()
                        conn_info["mqtt_client"].disconnect()
                    del self.terminal_uuid_connections[term_uuid]
                    
            # Очистим соединения VTE, которых уже нет
            for vte in list(self.mqtt_connections.keys()):
                vte_exists = False
                for term in Terminator().terminals:
                    if term.get_vte() == vte:
                        vte_exists = True
                        break
                
                if not vte_exists:
                    # VTE больше не существует, удаляем информацию
                    del self.mqtt_connections[vte]
                    
        except Exception as e:
            sys.stderr.write(f"Error updating terminal connections: {str(e)}\n")
    
    def update_button_state(self, terminal_uuid, connected=False, error=False):
        """Обновляет состояние кнопки MQTT в заголовке"""
        if terminal_uuid not in self.terminal_buttons:
            return
            
        button = self.terminal_buttons[terminal_uuid]
        image = button.get_image()
        
        if error:
            # Состояние ошибки
            image.set_from_icon_name('dialog-error', Gtk.IconSize.MENU)
            button.set_tooltip_text(_("MQTT: Connection Error"))
        elif connected:
            # Подключено
            image.set_from_icon_name('network-transmit-receive', Gtk.IconSize.MENU)
            conn_info = self.get_connection_info(terminal_uuid)
            if conn_info:
                button.set_tooltip_text(_(f"MQTT Connected: {conn_info['broker']}:{conn_info['port']}"))
        else:
            # Не подключено
            image.set_from_icon_name('network-offline', Gtk.IconSize.MENU)
            button.set_tooltip_text(_("MQTT: Not Connected"))

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
            # Проверяем, есть ли соединение для этого терминала по его UUID
            terminal_uuid = None
            
            # Сначала попробуем получить UUID непосредственно из VTE терминала
            for term in Terminator().terminals:
                if term.get_vte() == terminal:
                    terminal_uuid = term.uuid.urn
                    # Обновляем userdata для MQTT клиента, чтобы всегда была актуальная ссылка на терминал
                    if terminal_uuid in self.terminal_uuid_connections:
                        mqtt_client = self.terminal_uuid_connections[terminal_uuid]["mqtt_client"]
                        # Проверяем, изменились ли userdata
                        if mqtt_client._userdata.get('terminal') != term:
                            mqtt_client._userdata = {'terminal': term}
                    break
                    
            if not terminal_uuid or terminal_uuid not in self.terminal_uuid_connections:
                # Если не нашли соответствие, то возможно этот VTE больше не привязан к терминалу
                return
                
            conn_info = self.terminal_uuid_connections[terminal_uuid]
            
            # Only continue if we're connected
            if not conn_info["mqtt_client"].is_connected():
                self.update_button_state(terminal_uuid, False)
                return
                
            # Если VTE терминала изменился, обновим его в соединении
            for term in Terminator().terminals:
                if term.uuid.urn == terminal_uuid:
                    vte_terminal = term.get_vte()
                    if vte_terminal != terminal:
                        # VTE изменился, обновим обработчики сигналов
                        try:
                            if terminal in self.mqtt_connections:
                                terminal.disconnect(self.mqtt_connections[terminal]["handler_id"])
                                del self.mqtt_connections[terminal]
                        except:
                            pass
                            
                        # Подключим новый обработчик
                        handler_id = vte_terminal.connect('contents-changed', 
                                                      lambda vte: self.mqtt_publish(vte))
                        self.mqtt_connections[vte_terminal] = {
                            "handler_id": handler_id,
                            "terminal_uuid": terminal_uuid
                        }
                        
                        # Обновляем информацию о текущем состоянии курсора
                        (col, row) = vte_terminal.get_cursor_position()
                        conn_info["col"] = col
                        conn_info["row"] = row
                        return
            
            # Если соответствие найдено, работаем как обычно
            last_saved_col = conn_info["col"]
            last_saved_row = conn_info["row"]
            (col, row) = terminal.get_cursor_position()
            
            # Only send data when there's enough new content
            if row - last_saved_row < 1:  # Changed for more frequent updates
                return
                
            content = self.extract_content(terminal, last_saved_row, last_saved_col, row, col)
            if content:
                # Don't send the last char (usually '\n')
                conn_info["mqtt_client"].publish(
                    conn_info["pub_topic"],
                    content[:-1]
                )
                # Обновляем состояние кнопки при успешной отправке
                self.update_button_state(terminal_uuid, True)
                
            conn_info["col"] = col
            conn_info["row"] = row
        except Exception as e:
            sys.stderr.write(f"MQTT Publisher error: {str(e)}\n")
            # Обновляем состояние кнопки при ошибке
            if terminal_uuid:
                self.update_button_state(terminal_uuid, False, True)

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
                
                # Используем UUID терминала для создания уникального ID клиента с добавлением timestamp
                terminal_uuid = terminal.uuid.urn
                import time
                timestamp = int(time.time())
                client_id = f"terminator-{terminal_uuid}-{timestamp}"
                
                dbg(f"Creating MQTT client with ID: {client_id}")
                
                # Create MQTT client с включенным clean_session, чтобы избежать получения сохраненных сообщений
                mqtt_client = mqtt.Client(client_id=client_id, 
                                         clean_session=True,  # Всегда создавать новую сессию
                                         userdata={'terminal': terminal})
                
                # Set credentials if provided
                if username:
                    mqtt_client.username_pw_set(username, password)
                
                # Set up callbacks
                mqtt_client.on_message = self.on_mqtt_message
                mqtt_client.on_connect = self.on_mqtt_connect
                mqtt_client.on_disconnect = self.on_mqtt_disconnect
                mqtt_client.on_subscribe = self.on_mqtt_subscribe
                
                # Устанавливаем дополнительные MQTT опции для предотвращения дублирования сообщений
                # Отключаем автоматическую повторную подписку при переподключении
                mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)
                
                # Connect to broker
                dbg(f"Connecting to MQTT broker: {broker}:{port}")
                mqtt_client.connect_async(broker, port)
                
                # Start the background thread
                dbg(f"Starting MQTT loop")
                mqtt_client.loop_start()
                
                # Store connection info in UUID-based словаре
                vte_terminal = terminal.get_vte()
                (col, row) = vte_terminal.get_cursor_position()
                
                # Отключаем предыдущее соединение, если оно было
                if terminal_uuid in self.terminal_uuid_connections:
                    old_client = self.terminal_uuid_connections[terminal_uuid]["mqtt_client"]
                    try:
                        dbg(f"Stopping previous MQTT connection for {terminal_uuid}")
                        old_client.unsubscribe(self.terminal_uuid_connections[terminal_uuid]["sub_topic"])
                        old_client.loop_stop()
                        old_client.disconnect()
                    except:
                        pass
                
                self.terminal_uuid_connections[terminal_uuid] = {
                    "mqtt_client": mqtt_client,
                    "broker": broker,
                    "port": port,
                    "pub_topic": pub_topic,
                    "sub_topic": sub_topic,
                    "col": col,
                    "row": row
                }
                
                # Connect the contents-changed signal for publishing and store
                # the handler ID для VTE
                handler_id = vte_terminal.connect('contents-changed', 
                                           lambda vte: self.mqtt_publish(vte))
                                           
                # Удаляем предыдущие обработчики для этого VTE, если они были
                if vte_terminal in self.mqtt_connections:
                    try:
                        vte_terminal.disconnect(self.mqtt_connections[vte_terminal]["handler_id"])
                    except:
                        pass
                
                self.mqtt_connections[vte_terminal] = {
                    "handler_id": handler_id,
                    "terminal_uuid": terminal_uuid
                }
                
                # Обновляем состояние кнопки "ожидание подключения"
                self.update_button_state(terminal_uuid, False)
                
            except Exception as e:
                dbg(f"Error in configure_mqtt: {str(e)}")
                error = Gtk.MessageDialog(None, Gtk.DialogFlags.MODAL, 
                                         Gtk.MessageType.ERROR,
                                         Gtk.ButtonsType.OK, 
                                         f"Error connecting to MQTT broker: {str(e)}")
                error.set_transient_for(dialog)
                error.run()
                error.destroy()
                
                # Обновляем состояние кнопки при ошибке
                self.update_button_state(terminal_uuid, False, True)
        
        # Закрываем диалог
        dialog.destroy()
        
        # Восстанавливаем фокус терминала после закрытия диалогового окна
        self.focus_related_terminal(terminal)

    def on_mqtt_subscribe(self, client, userdata, mid, granted_qos):
        """Обработчик события успешной подписки на топик"""
        dbg(f"Successfully subscribed to topic, MID: {mid}, QoS: {granted_qos}")
        if userdata and 'terminal' in userdata:
            terminal = userdata['terminal']
            try:
                terminal_uuid = terminal.uuid.urn
                if terminal_uuid in self.terminal_uuid_connections:
                    # Подписка успешна, обновляем состояние кнопки
                    GLib.idle_add(lambda: self.update_button_state(terminal_uuid, True))
            except Exception as e:
                dbg(f"Error in on_mqtt_subscribe: {str(e)}")
    
    def on_mqtt_connect(self, client, userdata, flags, rc):
        """Обработчик успешного подключения к MQTT брокеру"""
        dbg(f"MQTT Connect callback with result code: {rc}")
        if not userdata or 'terminal' not in userdata:
            dbg("No valid terminal in userdata")
            return
            
        terminal = userdata['terminal']
        try:
            terminal_uuid = terminal.uuid.urn
            dbg(f"Terminal UUID in on_mqtt_connect: {terminal_uuid}")
            
            # Обновляем состояние кнопки на активное соединение
            GLib.idle_add(lambda: self.update_button_state(terminal_uuid, True))
            
            # Подписываемся на топик при успешном подключении
            if terminal_uuid in self.terminal_uuid_connections:
                sub_topic = self.terminal_uuid_connections[terminal_uuid]["sub_topic"]
                dbg(f"Subscribing to topic on connect: {sub_topic}")
                result, mid = client.subscribe(sub_topic)
                dbg(f"Subscribe result: {result}, Message ID: {mid}")
        except Exception as e:
            dbg(f"Error in on_mqtt_connect: {str(e)}")
    
    def on_mqtt_disconnect(self, client, userdata, rc):
        """Обработчик отключения от MQTT брокера"""
        dbg(f"MQTT Disconnect callback with result code: {rc}")
        if not userdata or 'terminal' not in userdata:
            dbg("No valid terminal in userdata")
            return
            
        terminal = userdata['terminal']
        try:
            terminal_uuid = terminal.uuid.urn
            dbg(f"Terminal UUID in on_mqtt_disconnect: {terminal_uuid}")
            
            # Обновляем состояние кнопки на отключенное соединение
            GLib.idle_add(lambda: self.update_button_state(terminal_uuid, False))
        except Exception as e:
            dbg(f"Error in on_mqtt_disconnect: {str(e)}")

    def stop_mqtt(self, _widget, terminal):
        """ Stop MQTT connection """
        terminal_uuid = terminal.uuid.urn
        
        if terminal_uuid in self.terminal_uuid_connections:
            # Отключаем все обработчики сигналов для этого терминала
            vte_terminal = terminal.get_vte()
            
            # Отключаем сигналы от текущего VTE
            if vte_terminal in self.mqtt_connections:
                try:
                    vte_terminal.disconnect(self.mqtt_connections[vte_terminal]["handler_id"])
                except:
                    pass
                del self.mqtt_connections[vte_terminal]
            
            # Отключаем все сигналы, связанные с этим UUID
            # (может быть создано несколько обработчиков при сплитах)
            for vte, info in list(self.mqtt_connections.items()):
                if info.get("terminal_uuid") == terminal_uuid:
                    try:
                        vte.disconnect(info["handler_id"])
                    except:
                        pass
                    del self.mqtt_connections[vte]
                    
            # Stop MQTT client
            self.terminal_uuid_connections[terminal_uuid]["mqtt_client"].loop_stop()
            self.terminal_uuid_connections[terminal_uuid]["mqtt_client"].disconnect()
            
            # Remove from connections dict
            del self.terminal_uuid_connections[terminal_uuid]
            
            # Обновляем состояние кнопки на отключенное соединение
            self.update_button_state(terminal_uuid, False)

    def on_mqtt_message(self, client, userdata, msg):
        """ Callback for received MQTT messages """
        dbg(f"MQTT message received from topic: {msg.topic}")
        
        if not userdata:
            dbg("MQTT: userdata is None!")
            return
            
        if 'terminal' not in userdata:
            dbg("MQTT: 'terminal' not in userdata!")
            return
            
        terminal = userdata['terminal']
        dbg(f"MQTT: terminal from userdata: {terminal}")
        
        try:
            terminal_uuid = terminal.uuid.urn
            dbg(f"MQTT: terminal UUID: {terminal_uuid}")
        except Exception as e:
            dbg(f"MQTT: Error getting UUID from terminal: {str(e)}")
            return
        
        # Проверяем, существует ли еще терминал в списке терминалов Terminator
        terminal_exists = False
        for term in Terminator().terminals:
            if term.uuid.urn == terminal_uuid:
                terminal = term  # Обновляем ссылку на терминал
                terminal_exists = True
                dbg(f"MQTT: Found matching terminal in Terminator terminals list")
                break
        
        if not terminal_exists:
            # Терминал был закрыт, нужно отключить MQTT слушателя
            dbg(f"MQTT: Terminal no longer exists, disconnecting client")
            try:
                client.disconnect()
                client.loop_stop()
                
                if terminal_uuid in self.terminal_uuid_connections:
                    del self.terminal_uuid_connections[terminal_uuid]
                    
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
                    
                dbg(f"MQTT message payload: {payload}")
                
                # Проверяем снова здесь, т.к. терминал мог быть закрыт между проверкой выше
                # и выполнением этого кода
                terminal_exists = False
                for term in Terminator().terminals:
                    if term.uuid.urn == terminal_uuid:
                        terminal = term  # Обновляем ссылку на терминал
                        terminal_exists = True
                        break
                
                if not terminal_exists:
                    dbg(f"MQTT: Terminal no longer exists in feed_to_terminal")
                    return False
                    
                # Совершенно удаляем любые завершающие переводы строки из входящего сообщения
                payload = payload.rstrip('\r\n')
                
                # А теперь добавляем ОДИН перевод строки для выполнения команды
                payload += '\n'
                
                # Дополнительная проверка перед использованием терминала
                vte_terminal = terminal.get_vte()
                if vte_terminal:
                    dbg(f"MQTT: Feeding message to VTE terminal: {payload}")
                    vte_terminal.feed_child(payload.encode())
                    dbg(f"MQTT: Message sent to terminal")
                else:
                    dbg(f"MQTT: No VTE terminal found")
                return False  # Don't repeat
            except Exception as e:
                sys.stderr.write(f"Error feeding MQTT message to terminal: {str(e)}\n")
                dbg(f"MQTT feed error: {str(e)}")
                return False
                
        # Schedule the GUI update in the main thread
        dbg(f"MQTT: Scheduling feed_to_terminal in GLib.idle_add")
        GLib.idle_add(feed_to_terminal)

    def on_terminal_closed(self, terminal):
        """Обработчик закрытия терминала - отключаем связанные MQTT соединения"""
        try:
            terminal_uuid = terminal.uuid.urn
            if terminal_uuid in self.terminal_uuid_connections:
                dbg(f"Terminal closed, stopping MQTT connections for {terminal}")
                
                # Отключаем все обработчики сигналов для этого терминала
                vte_terminal = terminal.get_vte()
                
                # Отключаем сигналы от текущего VTE
                if vte_terminal in self.mqtt_connections:
                    try:
                        vte_terminal.disconnect(self.mqtt_connections[vte_terminal]["handler_id"])
                    except:
                        pass
                    del self.mqtt_connections[vte_terminal]
                
                # Отключаем все сигналы, связанные с этим UUID
                for vte, info in list(self.mqtt_connections.items()):
                    if info.get("terminal_uuid") == terminal_uuid:
                        try:
                            vte.disconnect(info["handler_id"])
                        except:
                            pass
                        del self.mqtt_connections[vte]
                        
                # Stop MQTT client
                self.terminal_uuid_connections[terminal_uuid]["mqtt_client"].loop_stop()
                self.terminal_uuid_connections[terminal_uuid]["mqtt_client"].disconnect()
                
                # Remove from connections dict
                del self.terminal_uuid_connections[terminal_uuid]
                
                # Удаляем кнопку из списка
                if terminal_uuid in self.terminal_buttons:
                    del self.terminal_buttons[terminal_uuid]
                
        except Exception as e:
            sys.stderr.write(f"Error cleaning up MQTT on terminal close: {str(e)}\n")
            
    # Добавляем метод для обработки события сплита
    def on_terminal_split(self, terminal, orientation):
        """Обработчик события разделения терминала - копируем настройки MQTT"""
        dbg(f"Terminal split event in MQTT plugin")

    def configure_or_manage_mqtt(self, _widget, terminal):
        """Обработчик нажатия на пункт меню MQTT Feed"""
        terminal_uuid = terminal.uuid.urn
        is_connected = self.is_terminal_connected(terminal_uuid)
        
        if is_connected:
            # Если соединение уже установлено, показываем диалог управления
            self.show_mqtt_status_dialog(_widget.get_toplevel(), terminal)
        else:
            # Если соединения нет, запускаем настройку нового соединения
            self.configure_mqtt(_widget, terminal)
            
    def show_mqtt_status_dialog(self, parent, terminal):
        """Показывает диалог с информацией о текущем соединении MQTT"""
        terminal_uuid = terminal.uuid.urn
        conn_info = self.get_connection_info(terminal_uuid)
        
        if not conn_info:
            return
            
        dialog = Gtk.Dialog(
            title=_("MQTT Connection Status"),
            transient_for=parent,
            flags=0,
            buttons=(
                _("Disconnect"), Gtk.ResponseType.CANCEL,
                _("Close"), Gtk.ResponseType.OK
            )
        )
        dialog.set_default_size(400, 200)
        dialog.set_border_width(10)
        
        # Добавляем информацию о соединении
        grid = Gtk.Grid()
        grid.set_row_spacing(6)
        grid.set_column_spacing(12)
        grid.set_border_width(10)
        
        row = 0
        
        # Статус соединения
        status_label = Gtk.Label(label="<b>Status:</b>")
        status_label.set_use_markup(True)
        status_label.set_halign(Gtk.Align.END)
        
        connected = conn_info["mqtt_client"].is_connected()
        status_value = Gtk.Label()
        if connected:
            status_value.set_markup("<span foreground='green'>Connected</span>")
        else:
            status_value.set_markup("<span foreground='red'>Disconnected</span>")
        
        grid.attach(status_label, 0, row, 1, 1)
        grid.attach(status_value, 1, row, 1, 1)
        row += 1
        
        # Брокер
        broker_label = Gtk.Label(label="<b>Broker:</b>")
        broker_label.set_use_markup(True)
        broker_label.set_halign(Gtk.Align.END)
        broker_value = Gtk.Label(label=f"{conn_info['broker']}:{conn_info['port']}")
        broker_value.set_halign(Gtk.Align.START)
        
        grid.attach(broker_label, 0, row, 1, 1)
        grid.attach(broker_value, 1, row, 1, 1)
        row += 1
        
        # Темы
        pub_label = Gtk.Label(label="<b>Publishing to:</b>")
        pub_label.set_use_markup(True)
        pub_label.set_halign(Gtk.Align.END)
        pub_value = Gtk.Label(label=conn_info['pub_topic'])
        pub_value.set_halign(Gtk.Align.START)
        
        grid.attach(pub_label, 0, row, 1, 1)
        grid.attach(pub_value, 1, row, 1, 1)
        row += 1
        
        sub_label = Gtk.Label(label="<b>Subscribed to:</b>")
        sub_label.set_use_markup(True)
        sub_label.set_halign(Gtk.Align.END)
        sub_value = Gtk.Label(label=conn_info['sub_topic'])
        sub_value.set_halign(Gtk.Align.START)
        
        grid.attach(sub_label, 0, row, 1, 1)
        grid.attach(sub_value, 1, row, 1, 1)
        row += 1
        
        # Добавляем инструкции по использованию
        help_label = Gtk.Label()
        help_text = "\n<small>"
        help_text += "• Terminal output is published to the publish topic\n"
        help_text += "• Messages received on subscription topic are sent as input to the terminal\n"
        help_text += "• You can test with mosquitto tools:\n"
        help_text += f"  - mosquitto_pub -t {conn_info['sub_topic']} -m \"ls -la\"\n"
        help_text += f"  - mosquitto_sub -t {conn_info['pub_topic']}"
        help_text += "</small>"
        help_label.set_markup(help_text)
        help_label.set_halign(Gtk.Align.START)
        
        grid.attach(help_label, 0, row, 2, 1)
        
        content_area = dialog.get_content_area()
        content_area.add(grid)
        
        dialog.show_all()
        response = dialog.run()
        
        if response == Gtk.ResponseType.CANCEL:
            # Отключение соединения
            self.stop_mqtt(None, terminal)
        
        dialog.destroy()
        
        # Восстанавливаем фокус терминала после закрытия диалога
        self.focus_related_terminal(terminal)

    def update_mqtt_userdata(self, terminal_uuid, terminal):
        """Обновляет ссылку на терминал в userdata для MQTT клиента"""
        if terminal_uuid in self.terminal_uuid_connections:
            mqtt_client = self.terminal_uuid_connections[terminal_uuid]["mqtt_client"]
            if mqtt_client._userdata.get('terminal') != terminal:
                dbg(f"Updating MQTT userdata for terminal {terminal_uuid}")
                mqtt_client._userdata = {'terminal': terminal}
                return True
        return False

    def focus_related_terminal(self, terminal):
        """Восстанавливает фокус на терминале после закрытия диалогового окна"""
        if terminal:
            dbg(f"Restoring focus to terminal: {terminal.uuid.urn}")
            # Искусственно генерируем событие получения фокуса
            GLib.idle_add(lambda: terminal.on_vte_focus_in(terminal.vte, None))
            # Устанавливаем фокус на VTE
            terminal.grab_focus()
            return True
        return False


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