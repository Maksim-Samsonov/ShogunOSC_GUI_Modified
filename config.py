"""
Файл с конфигурационными параметрами и проверкой зависимостей.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from PyQt5.QtCore import QSettings

# Директория конфигурации
CONFIG_DIR = os.path.expanduser("~/.shogun_osc")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")

# Настройки приложения по умолчанию
DEFAULT_SETTINGS = {
    "dark_mode": False,
    "osc_ip": "0.0.0.0",
    "osc_port": 5555,
    "osc_enabled": True,
    "osc_broadcast_port": 9000,  # Порт для отправки OSC-сообщений
    "osc_broadcast_ip": "255.255.255.255",  # IP для отправки OSC-сообщений (широковещательный)
    "capture_folder": "",  # Папка для записи захватов
    "capture_name": "",    # Имя захвата по умолчанию
    "capture_description": ""  # Описание захвата по умолчанию
}

# Менеджер настроек
settings = QSettings("ShogunOSC", "ShogunOSCApp")

def load_settings() -> Dict[str, Any]:
    """
    Загрузка настроек приложения
    
    Returns:
        Dict[str, Any]: Словарь с настройками приложения
    """
    # Создаем каталог конфигурации если не существует
    if not os.path.exists(CONFIG_DIR):
        try:
            os.makedirs(CONFIG_DIR)
        except OSError as e:
            logging.getLogger('ShogunOSC').error(f"Не удалось создать каталог конфигурации: {e}")
    
    settings_dict = DEFAULT_SETTINGS.copy()
    
    # Используем QSettings для хранения настроек
    for key in DEFAULT_SETTINGS.keys():
        if settings.contains(key):
            value = settings.value(key)
            # Преобразуем строковые значения 'true'/'false' в булевы
            if isinstance(value, str) and value.lower() in ['true', 'false']:
                value = value.lower() == 'true'
            # Преобразуем числовые значения из строк в числа
            elif key in ['osc_port', 'osc_broadcast_port'] and isinstance(value, str) and value.isdigit():
                value = int(value)
            settings_dict[key] = value
    
    return settings_dict

def save_settings(settings_dict: Dict[str, Any]) -> None:
    """
    Сохранение настроек приложения
    
    Args:
        settings_dict: Словарь с настройками для сохранения
    """
    try:
        for key, value in settings_dict.items():
            settings.setValue(key, value)
        settings.sync()
    except Exception as e:
        logging.getLogger('ShogunOSC').error(f"Ошибка при сохранении настроек: {e}")

# Загружаем настройки
app_settings = load_settings()

# Флаг темной темы
DARK_MODE = app_settings.get("dark_mode", False)

# Проверка зависимостей
IMPORT_SUCCESS = True
IMPORT_ERROR = ""

try:
    # Библиотеки для Shogun Live
    from vicon_core_api import Client
    from shogun_live_api import CaptureServices
    
    # Библиотеки для OSC
    from pythonosc import dispatcher, osc_server
except ImportError as e:
    IMPORT_SUCCESS = False
    IMPORT_ERROR = str(e)

# Настройки OSC-сервера из параметров приложения
DEFAULT_OSC_IP = app_settings.get("osc_ip", "0.0.0.0")
DEFAULT_OSC_PORT = app_settings.get("osc_port", 5555)
DEFAULT_OSC_BROADCAST_IP = app_settings.get("osc_broadcast_ip", "255.255.255.255")
DEFAULT_OSC_BROADCAST_PORT = app_settings.get("osc_broadcast_port", 9000)

# OSC-адреса для управления Shogun Live
OSC_START_RECORDING = "/RecordStartShogunLive"
OSC_STOP_RECORDING = "/RecordStopShogunLive"
OSC_CAPTURE_NAME_CHANGED = "/ShogunLiveCaptureName"  # Адрес для уведомления об изменении имени захвата
OSC_SET_CAPTURE_NAME = "/SetCaptureName"  # Установка имени захвата
OSC_SET_CAPTURE_FOLDER = "/SetCaptureFolder"  # Установка директории для захвата
OSC_SET_CAPTURE_DESCRIPTION = "/SetCaptureDescription"  # Установка описания захвата
OSC_CAPTURE_ERROR = "/ShogunLiveCaptureError"  # Уведомление об ошибке записи

# Настройки логирования
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
LOG_MAX_LINES = 1000

# Настройки для проверки соединения с Shogun Live
MAX_RECONNECT_ATTEMPTS = 10
BASE_RECONNECT_DELAY = 1
MAX_RECONNECT_DELAY = 15

# Названия статусов для понятного отображения
STATUS_CONNECTED = "Подключено"
STATUS_DISCONNECTED = "Отключено"
STATUS_RECORDING_ACTIVE = "Активна"
STATUS_RECORDING_INACTIVE = "Не активна"

# Версия приложения
APP_VERSION = "1.1.0"

def get_app_version() -> str:
    """
    Возвращает текущую версию приложения
    
    Returns:
        str: Версия приложения
    """
    return APP_VERSION