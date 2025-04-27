# Плагины Terminator

## Обзор системы плагинов

Terminator поддерживает различные типы плагинов для расширения своей функциональности. В этом документе описывается архитектура плагинов Terminator, с особым фокусом на плагины с кнопками, которые добавляются в верхнюю панель (заголовок) терминала.

## Типы плагинов

Terminator поддерживает несколько типов плагинов, определяемых их "возможностями" (capabilities):

1. `terminal_menu` - Добавляет элементы в контекстное меню терминала
2. `url_handler` - Обрабатывает специальные URL в терминале
3. `titlebar_button` - Добавляет кнопки в заголовок терминала (новый тип)

## Архитектура системы плагинов

Система плагинов Terminator базируется на следующих компонентах:

- `terminatorlib/plugin.py` - Основной файл, содержащий классы для регистрации и управления плагинами
- `terminatorlib/plugins/` - Директория, где располагаются плагины
- `PluginRegistry` - Класс, отвечающий за загрузку и управление плагинами
- `Plugin` - Базовый класс для всех плагинов

### Регистрация плагинов

Плагины регистрируются через механизм, определенный в файле `plugin.py`:

```python
class PluginRegistry(Borg):
    """A class to hold a registry of plugins that we can find"""
    ...
    def load_plugins(self, force=False):
        """Load all plugins we can find"""
        ...
```

Каждый плагин должен определить глобальную переменную `AVAILABLE`, которая содержит список классов плагинов, доступных в файле.

## Плагины с кнопками в заголовке терминала

### Интерфейс TitlebarButton

Плагины, добавляющие кнопки в заголовок терминала, наследуются от класса `TitlebarButton`:

```python
class TitlebarButton(Plugin):
    """Base class for titlebar button objects"""
    capabilities = ['titlebar_button']
    handler_name = None
    # ...
```

### Процесс добавления кнопок в заголовок

1. В файле `titlebar.py` при инициализации заголовка происходит загрузка плагинов с возможностью `titlebar_button`:

```python
# Добавляем поддержку кнопок от плагинов
self.plugin_buttons = {}
try:
    from terminatorlib.plugin import PluginRegistry
    registry = PluginRegistry()
    registry.load_plugins()
    plugins = registry.get_plugins_by_capability('titlebar_button')
    for button_plugin in plugins:
        try:
            button = button_plugin.get_button(terminal)
            if button:
                self.plugin_buttons[button_plugin.__class__.__name__] = button
                hbox.pack_end(button, False, False, 2)
                button.show_all()
        except Exception as plugin_ex:
            dbg('Ошибка при добавлении кнопки %s: %s' % (button_plugin.__class__.__name__, plugin_ex))
except Exception as ex:
    dbg('Ошибка при загрузке кнопок для заголовка: %s' % ex)
```

2. Плагин должен реализовать метод `get_button(terminal)`, который создает и возвращает виджет кнопки GTK.

### Динамическое обновление заголовка

При перезагрузке терминала или изменении его конфигурации происходит обновление заголовка с помощью метода `delayed_load_plugins()`:

```python
def delayed_load_plugins(self):
    """Загрузить плагины с задержкой после инициализации терминала"""
    dbg('Delayed loading plugins for terminal UUID: %s' % self.uuid.urn)
    self.load_plugins(force = True)
    # ... дополнительный код для обновления связей с плагинами
    return False
```

## Пример создания плагина с кнопкой в заголовке

### Пример: MQTT Logger плагин

Ниже приведен пример структуры плагина `MQTTLogger`, который добавляет кнопку в заголовок терминала для работы с MQTT:

```python
# mqttlogger.py
import terminatorlib.plugin as plugin
from gi.repository import Gtk

AVAILABLE = ['MQTTLogger']

class MQTTLogger(plugin.TitlebarButton):
    capabilities = ['titlebar_button']
    
    def __init__(self):
        plugin.TitlebarButton.__init__(self)
        # Инициализация плагина
    
    def get_button(self, terminal):
        """Создает и возвращает кнопку для панели заголовка терминала"""
        button = Gtk.Button()
        image = Gtk.Image()
        
        # Настройка кнопки...
        
        button.set_image(image)
        button.set_relief(Gtk.ReliefStyle.NONE)
        
        # Привязка обработчиков событий
        button.connect('clicked', self.on_button_clicked, terminal)
        
        return button
        
    def on_button_clicked(self, widget, terminal):
        """Обработчик нажатия на кнопку"""
        # Обработка нажатия...
```

## Обработка событий терминала в плагинах

Плагины с кнопками могут подписываться на различные события терминала:

1. `terminal.connect('close-term', self.on_terminal_closed)` - Событие закрытия терминала
2. `vte_terminal.connect('contents-changed', self.on_content_changed)` - Изменение содержимого терминала

## Жизненный цикл плагина и связь с терминалом

### Инициализация

1. Плагины загружаются при старте Terminator
2. При создании нового терминала вызывается метод `get_button(terminal)` для каждого плагина с возможностью `titlebar_button`
3. Кнопки добавляются в заголовок терминала

### Обновление состояния

Плагины должны самостоятельно обновлять состояние своих кнопок в ответ на события терминала или внешние события.

### Завершение работы

При закрытии терминала плагин должен корректно освобождать ресурсы, отключать обработчики событий и закрывать соединения.

## Рекомендации по разработке плагинов с кнопками для заголовка

1. **Минимальный размер интерфейса**: Кнопки должны быть компактными и занимать минимум места в заголовке
2. **Корректная работа с UUID терминала**: Используйте UUID для идентификации терминалов, а не ссылки на объекты
3. **Обработка пересоздания заголовка**: Учитывайте, что заголовок может быть пересоздан при изменении настроек
4. **Обновление userdata**: При обновлении заголовка обновляйте ссылки на терминал в данных плагина
5. **Корректное освобождение ресурсов**: Отслеживайте закрытие терминалов и корректно освобождайте ресурсы

## Стилизация кнопок для компактного отображения

Для создания компактных кнопок в заголовке рекомендуется использовать CSS:

```python
css = Gtk.CssProvider()
css.load_from_data(b"button { min-height: 0px; padding: 0px 2px; }")
button.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
```

Также рекомендуется отключать рамку кнопок:

```python
button.set_relief(Gtk.ReliefStyle.NONE)
```

## Ограничения и особенности

1. **Возможные конфликты**: При наличии множества плагинов с кнопками заголовок может стать слишком загруженным
2. **Пересоздание заголовка**: При изменении настроек терминала заголовок может быть пересоздан, что требует корректного обновления ссылок
3. **Уникальность идентификаторов**: Всегда используйте UUID терминала для хранения данных, связанных с конкретным терминалом

## Заключение

Система плагинов с кнопками в заголовке терминала предоставляет гибкий способ расширения функциональности Terminator. Этот интерфейс позволяет добавлять интерактивные элементы управления непосредственно в заголовок терминала, обеспечивая удобный доступ к дополнительным функциям.