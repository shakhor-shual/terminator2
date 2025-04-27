# Terminator by Chris Jones <cmsj@tenshu.net>
# GPL v2 only
"""titlebar.py - classes necessary to provide a terminal title bar"""

from gi.repository import Gtk, Gdk
from gi.repository import GObject
from gi.repository import Pango

from .version import APP_NAME
from .util import dbg
from .terminator import Terminator
from .editablelabel import EditableLabel
from .translation import _

# pylint: disable-msg=R0904
# pylint: disable-msg=W0613
class Titlebar(Gtk.EventBox):
    """Class implementing the Titlebar widget"""

    terminator = None
    terminal = None
    config = None
    oldtitle = None
    termtext = None
    sizetext = None
    label = None
    ebox = None
    groupicon = None
    grouplabel = None
    groupentry = None
    bellicon = None

    __gsignals__ = {
            'clicked': (GObject.SignalFlags.RUN_LAST, None, ()),
            'edit-done': (GObject.SignalFlags.RUN_LAST, None, ()),
            'create-group': (GObject.SignalFlags.RUN_LAST, None,
                (GObject.TYPE_STRING,)),
    }

    def __init__(self, terminal):
        """Class initialiser"""
        GObject.GObject.__init__(self)

        self.terminator = Terminator()
        self.terminal = terminal
        self.config = self.terminal.config

        # Уменьшаем отступы и размер шрифта для более компактного заголовка
        self.set_border_width(0)  # Уменьшаем внешние отступы
        
        self.label = EditableLabel()
        self.label.connect('edit-done', self.on_edit_done)
        self.label.set_margin_top(0)    # Уменьшаем внутренние отступы
        self.label.set_margin_bottom(0)
        self.label.set_no_show_all(True)  # Скрываем по умолчанию
        self.label.hide()  # Скрываем надпись
        
        # Создаем элементы для группировки, но не показываем их в заголовке
        # (для совместимости с функциями группировки)
        self.ebox = Gtk.EventBox()
        grouphbox = Gtk.HBox()
        
        # Настройка размеров элементов группы
        grouphbox.set_spacing(1)  # Уменьшаем расстояние между элементами
        
        self.grouplabel = Gtk.Label(ellipsize='end')
        self.grouplabel.set_margin_top(0)
        self.grouplabel.set_margin_bottom(0)
        
        self.groupicon = Gtk.Image()
        self.bellicon = Gtk.Image()
        self.bellicon.set_no_show_all(True)

        self.groupentry = Gtk.Entry()
        self.groupentry.set_no_show_all(True)
        self.groupentry.connect('focus-out-event', self.groupentry_cancel)
        self.groupentry.connect('activate', self.groupentry_activate)
        self.groupentry.connect('key-press-event', self.groupentry_keypress)
        
        # Уменьшаем высоту поля ввода
        css = Gtk.CssProvider()
        css.load_from_data(b"entry { min-height: 0px; padding-top: 0px; padding-bottom: 0px; }")
        self.groupentry.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        groupsend_type = self.terminator.groupsend_type
        if self.terminator.groupsend == groupsend_type['all']:
            icon_name = 'all'
        elif self.terminator.groupsend == groupsend_type['group']:
            icon_name = 'group'
        elif self.terminator.groupsend == groupsend_type['off']:
            icon_name = 'off'
        self.set_from_icon_name('_active_broadcast_%s' % icon_name, 
                Gtk.IconSize.MENU)

        grouphbox.pack_start(self.groupicon, False, True, 0)
        grouphbox.pack_start(self.grouplabel, False, True, 0)
        grouphbox.pack_start(self.groupentry, False, True, 0)

        self.ebox.add(grouphbox)
        self.ebox.set_no_show_all(True)  # Скрываем элемент группы
        self.ebox.hide()                 # Скрываем элемент группы
        
        self.bellicon.set_from_icon_name('terminal-bell', Gtk.IconSize.MENU)

        # Создаем основной контейнер
        hbox = Gtk.HBox()
        hbox.set_spacing(1)  # Уменьшаем расстояние между элементами
        
        # Левая часть заголовка (встроенные функции)
        left_box = Gtk.HBox()
        left_box.set_spacing(1)
        
        # Правая часть заголовка (плагины и индикаторы)
        right_box = Gtk.HBox()
        right_box.set_spacing(1)
        
        # Добавляем элементы в левую часть
        # НЕ добавляем self.ebox в left_box, так как мы хотим скрыть его
        
        # Создаем универсальную кнопку масштабирования (максимизация/восстановление)
        self.zoom_button = Gtk.Button()
        self.zoom_button.set_relief(Gtk.ReliefStyle.NONE)
        self.zoom_icon = Gtk.Image()
        
        # Устанавливаем начальное состояние (по умолчанию - максимизация)
        self.update_zoom_button_state(False)
        
        # Привязываем обработчик нажатия
        self.zoom_button.connect('clicked', self.on_zoom_button_clicked)
        
        # Применяем CSS для компактного вида
        zoom_css = Gtk.CssProvider()
        zoom_css.load_from_data(b"button { min-height: 0px; padding: 0px 2px; }")
        self.zoom_button.get_style_context().add_provider(zoom_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        # Создаем кнопку для сплита авто
        split_button = Gtk.Button()
        split_button.set_relief(Gtk.ReliefStyle.NONE)
        split_icon = Gtk.Image()
        split_icon.set_from_icon_name('view-grid-symbolic', Gtk.IconSize.MENU)
        split_button.set_image(split_icon)
        split_button.set_tooltip_text(_('Split terminal automatically'))
        split_button.connect('clicked', lambda w: self.terminal.key_split_auto())
        
        # Применяем CSS для компактного вида
        split_css = Gtk.CssProvider()
        split_css.load_from_data(b"button { min-height: 0px; padding: 0px 2px; }")
        split_button.get_style_context().add_provider(split_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        # Добавляем кнопки в левую часть заголовка
        left_box.pack_start(self.zoom_button, False, False, 0)
        left_box.pack_start(split_button, False, False, 0)
        
        # Добавляем индикатор звонка в правую часть
        right_box.pack_start(self.bellicon, False, False, 0)
        
        # Загружаем кнопки плагинов в правую часть
        self.plugin_buttons = {}
        try:
            from terminatorlib.plugin import PluginRegistry
            registry = PluginRegistry()
            registry.load_plugins()
            plugins = registry.get_plugins_by_capability('titlebar_button')
            for button_plugin in plugins:
                try:
                    dbg('Получаем кнопку от плагина: %s' % button_plugin.__class__.__name__)
                    button = button_plugin.get_button(terminal)
                    if button:
                        # Уменьшаем размер кнопок от плагинов
                        button.set_relief(Gtk.ReliefStyle.NONE)  # Убираем рамку для более компактного вида
                        css = Gtk.CssProvider()
                        css.load_from_data(b"button { min-height: 0px; padding: 0px 2px; }")
                        button.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
                        
                        self.plugin_buttons[button_plugin.__class__.__name__] = button
                        right_box.pack_end(button, False, False, 0)
                        button.show_all()
                except Exception as plugin_ex:
                    dbg('Ошибка при добавлении кнопки %s: %s' % (button_plugin.__class__.__name__, plugin_ex))
        except Exception as ex:
            dbg('Ошибка при загрузке кнопок для заголовка: %s' % ex)
        
        # Собираем левую и правую части в основной контейнер
        hbox.pack_start(left_box, False, True, 0)
        hbox.pack_end(right_box, False, True, 0)
        
        # Добавляем скрытый viewport с текстом в середину (не будет отображаться)
        viewport = Gtk.Viewport(hscroll_policy='natural')
        viewport.add(self.label)
        viewport.set_margin_top(0)
        viewport.set_margin_bottom(0)
        viewport.set_no_show_all(True)
        viewport.hide()
        
        self.add(hbox)
        
        # Добавляем CSS для всего заголовка, чтобы уменьшить его высоту
        css = Gtk.CssProvider()
        css.load_from_data(b"box { min-height: 0px; }")
        self.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        hbox.show_all()
        self.set_no_show_all(True)
        self.show()

        self.connect('button-press-event', self.on_clicked)
        
        # Подключаем обработчик изменения состояния терминала
        self.terminal.connect('unzoom', lambda w: self.update_zoom_button_state(False))
        self.terminal.connect('zoom', lambda w: self.update_zoom_button_state(True))
        self.terminal.connect('maximise', lambda w: self.update_zoom_button_state(True))
        
        # Обновляем начальное состояние кнопки после создания всех виджетов
        GObject.idle_add(self.update_button_sensitivity)
        
        # Вместо подписки на события создания и удаления терминалов,
        # которые не реализованы через систему сигналов,
        # добавляем периодическую проверку состояния
        GObject.timeout_add(1000, self.check_terminal_count)
    
    def update_zoom_button_state(self, is_zoomed):
        """Обновляет состояние и внешний вид кнопки масштабирования"""
        if is_zoomed:
            # Терминал увеличен - показываем кнопку восстановления
            self.zoom_icon.set_from_icon_name('view-restore-symbolic', Gtk.IconSize.MENU)
            self.zoom_button.set_tooltip_text(_('Restore all terminals'))
        else:
            # Терминал в обычном состоянии - показываем кнопку максимизации
            self.zoom_icon.set_from_icon_name('view-fullscreen-symbolic', Gtk.IconSize.MENU)
            self.zoom_button.set_tooltip_text(_('Maximize terminal'))
        
        self.zoom_button.set_image(self.zoom_icon)
        
        # После обновления иконки проверяем, нужно ли деактивировать кнопку
        self.update_button_sensitivity()
    
    def update_button_sensitivity(self):
        """Обновляет активность кнопки масштабирования в зависимости от количества терминалов"""
        # Получаем список всех терминалов в окне
        from terminatorlib.window import Window
        
        is_zoom_button_sensitive = False
        
        try:
            # Проходим по родительским объектам, чтобы найти Window
            parent = self.terminal.get_parent()
            while parent:
                if isinstance(parent, Window):
                    # Если нашли окно, получаем все терминалы из него
                    terminals = parent.get_terminals()
                    is_zoom_button_sensitive = len(terminals) > 1
                    break
                parent = parent.get_parent()
                
            # Если терминал в состоянии максимизации, кнопка всегда активна (для восстановления)
            if self.terminal.is_zoomed():
                is_zoom_button_sensitive = True
        except Exception as e:
            # Если что-то пошло не так, выводим отладочную информацию
            from terminatorlib.util import dbg
            dbg(f"Ошибка при обновлении состояния кнопки масштабирования: {str(e)}")
            # По умолчанию делаем кнопку активной, чтобы избежать блокировки функциональности
            is_zoom_button_sensitive = True
            
        # Применяем состояние активности к кнопке
        self.zoom_button.set_sensitive(is_zoom_button_sensitive)
    
    def on_zoom_button_clicked(self, widget):
        """Обработчик нажатия на кнопку масштабирования"""
        # Проверяем текущее состояние терминала
        if self.terminal.is_zoomed():
            # Если увеличен - восстанавливаем нормальный размер
            dbg('Restoring all terminals')
            self.terminal.unzoom()
            self.update_zoom_button_state(False)
        else:
            # Если нормальный размер - увеличиваем
            dbg('Maximizing terminal')
            self.terminal.key_toggle_zoom()
            self.update_zoom_button_state(True)
        
        # После изменения состояния проверяем активность кнопки
        self.update_button_sensitivity()

    def connect_icon(self, func):
        """Connect the supplied function to clicking on the group icon"""
        self.ebox.connect('button-press-event', func)

    def update(self, other=None):
        """Update our contents"""
        default_bg = False

        temp_heldtext_str = ''
        temp_sizetext_str = ''

        if self.terminal.is_held_open:
            temp_heldtext_str = _('[INACTIVE: Right-Click for Relaunch option] ')
        if not self.config['title_hide_sizetext']:
            temp_sizetext_str = " %s" % (self.sizetext)
        self.label.set_text("%s%s%s" % (temp_heldtext_str, self.termtext, temp_sizetext_str))

        if (not self.config['title_use_system_font']) and self.config['title_font']:
            title_font = Pango.FontDescription(self.config['title_font'])
        else:
            title_font = Pango.FontDescription(self.config.get_system_prop_font())
        self.label.modify_font(title_font)
        self.grouplabel.modify_font(title_font)

        if other:
            term = self.terminal
            terminator = self.terminator
            if other == 'window-focus-out':
                title_fg = self.config['title_inactive_fg_color']
                title_bg = self.config['title_inactive_bg_color']
                icon = '_receive_off'
                default_bg = True
                group_fg = self.config['title_inactive_fg_color']
                group_bg = self.config['title_inactive_bg_color']
            elif term != other and term.group and term.group == other.group:
                if terminator.groupsend == terminator.groupsend_type['off']:
                    title_fg = self.config['title_inactive_fg_color']
                    title_bg = self.config['title_inactive_bg_color']
                    icon = '_receive_off'
                    default_bg = True
                else:
                    title_fg = self.config['title_receive_fg_color']
                    title_bg = self.config['title_receive_bg_color']
                    icon = '_receive_on'
                group_fg = self.config['title_receive_fg_color']
                group_bg = self.config['title_receive_bg_color']
            elif term != other and not term.group or term.group != other.group:
                if terminator.groupsend == terminator.groupsend_type['all']:
                    title_fg = self.config['title_receive_fg_color']
                    title_bg = self.config['title_receive_bg_color']
                    icon = '_receive_on'
                else:
                    title_fg = self.config['title_inactive_fg_color']
                    title_bg = self.config['title_inactive_bg_color']
                    icon = '_receive_off'
                    default_bg = True
                group_fg = self.config['title_inactive_fg_color']
                group_bg = self.config['title_inactive_bg_color']
            else:
                # We're the active terminal
                title_fg = self.config['title_transmit_fg_color']
                title_bg = self.config['title_transmit_bg_color']
                if terminator.groupsend == terminator.groupsend_type['all']:
                    icon = '_active_broadcast_all'
                elif terminator.groupsend == terminator.groupsend_type['group']:
                    icon = '_active_broadcast_group'
                else:
                    icon = '_active_broadcast_off'
                group_fg = self.config['title_transmit_fg_color']
                group_bg = self.config['title_transmit_bg_color']

            self.label.modify_fg(Gtk.StateType.NORMAL,
                    Gdk.color_parse(title_fg))
            self.grouplabel.modify_fg(Gtk.StateType.NORMAL,
                    Gdk.color_parse(group_fg))
            self.modify_bg(Gtk.StateType.NORMAL, 
                    Gdk.color_parse(title_bg))
            if not self.get_desired_visibility():
                if default_bg == True:
                    color = term.get_style_context().get_background_color(Gtk.StateType.NORMAL)  # VERIFY FOR GTK3
                else:
                    color = Gdk.color_parse(title_bg)
            self.update_visibility()
            self.ebox.modify_bg(Gtk.StateType.NORMAL,
                    Gdk.color_parse(group_bg))
            self.set_from_icon_name(icon, Gtk.IconSize.MENU)

    def update_visibility(self):
        """Make the titlebar be visible or not"""
        if not self.get_desired_visibility():
            dbg('hiding titlebar')
            self.hide()
            self.label.hide()
        else:
            dbg('showing titlebar')
            self.show()
            self.label.show()

    def get_desired_visibility(self):
        """Returns True if the titlebar is supposed to be visible. False if
        not"""
        if self.editing() == True or self.terminal.group:
            dbg('implicit desired visibility')
            return(True)
        else:
            dbg('configured visibility: %s' % self.config['show_titlebar'])
            return(self.config['show_titlebar'])

    def set_from_icon_name(self, name, size = Gtk.IconSize.MENU):
        """Set an icon for the group label"""
        if not name:
            self.groupicon.hide()
            return
        
        self.groupicon.set_from_icon_name(APP_NAME + name, size)
        self.groupicon.show()

    def update_terminal_size(self, width, height):
        """Update the displayed terminal size"""
        self.sizetext = "%sx%s" % (width, height)
        self.update()

    def set_terminal_title(self, widget, title):
        """Update the terminal title"""
        self.termtext = title
        self.update()
        # Return False so we don't interrupt any chains of signal handling
        return False

    def set_group_label(self, name):
        """Set the name of the group"""
        if name:
            self.grouplabel.set_text(name)
            self.grouplabel.show()
        else:
            self.grouplabel.set_text('')
            self.grouplabel.hide()
        self.update_visibility()

    def on_clicked(self, widget, event):
        """Handle a click on the label"""
        self.show()
        self.label.show()
        self.emit('clicked')

    def on_edit_done(self, widget):
        """Re-emit an edit-done signal from an EditableLabel"""
        self.emit('edit-done')

    def editing(self):
        """Determine if we're currently editing a group name or title"""
        return(self.groupentry.get_property('visible') or self.label.editing())

    def create_group(self):
        """Create a new group"""
        if self.terminal.group:
            self.groupentry.set_text(self.terminal.group)
        else:
            self.groupentry.set_text(self.terminator.new_random_group())
        self.groupentry.show()
        self.grouplabel.hide()
        self.groupentry.grab_focus()
        self.update_visibility()

    def groupentry_cancel(self, widget, event):
        """Hide the group name entry"""
        self.groupentry.set_text('')
        self.groupentry.hide()
        self.grouplabel.show()
        self.get_parent().grab_focus()

    def groupentry_activate(self, widget):
        """Actually cause a group to be created"""
        groupname = self.groupentry.get_text() or None
        dbg('creating group: %s' % groupname)
        self.groupentry_cancel(None, None)
        last_focused_term=self.terminator.last_focused_term
        if self.terminal.targets_for_new_group:
            [term.titlebar.emit('create-group', groupname) for term in self.terminal.targets_for_new_group]
            self.terminal.targets_for_new_group = None
        else:
            self.emit('create-group', groupname)
        last_focused_term.grab_focus()
        self.terminator.focus_changed(last_focused_term)

    def groupentry_keypress(self, widget, event):
        """Handle keypresses on the entry widget"""
        key = Gdk.keyval_name(event.keyval)
        if key == 'Escape':
            self.groupentry_cancel(None, None)

    def icon_bell(self):
        """A bell signal requires we display our bell icon"""
        self.bellicon.show()
        GObject.timeout_add(1000, self.icon_bell_hide)

    def icon_bell_hide(self):
        """Handle a timeout which means we now hide the bell icon"""
        self.bellicon.hide()
        return(False)

    def get_custom_string(self):
        """If we have a custom string set, return it, otherwise None"""
        if self.label.is_custom():
            return(self.label.get_text())
        else:
            return(None)

    def set_custom_string(self, string):
        """Set a custom string"""
        self.label.set_text(string)
        self.label.set_custom()

    def check_terminal_count(self):
        """Периодически проверяет количество терминалов и обновляет состояние кнопки"""
        self.update_button_sensitivity()
        # Возвращаем True, чтобы продолжить периодические вызовы
        return True

GObject.type_register(Titlebar)
