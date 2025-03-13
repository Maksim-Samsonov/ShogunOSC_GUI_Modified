"""
Модуль OSC-сервера для приема и обработки OSC-сообщений.
"""

import asyncio
import logging
import threading
import socket
from datetime import datetime
from typing import Callable, Any, Optional
from PyQt5.QtCore import QThread, pyqtSignal

from pythonosc import dispatcher, osc_server, udp_client
import config

class OSCServer(QThread):
    """Поток OSC-сервера для приема и обработки OSC-сообщений"""
    message_signal = pyqtSignal(str, str)  # Сигнал для полученного OSC-сообщения (адрес, значение)
    
    def __init__(self, ip: str = "0.0.0.0", port: int = 5555, shogun_worker = None):
        super().__init__()
        self.logger = logging.getLogger('ShogunOSC')
        self.ip = ip
        self.port = port
        self.shogun_worker = shogun_worker
        self.running = True
        self.dispatcher = dispatcher.Dispatcher()
        self.server = None
        self._socket = None
        self.osc_client = None
        
        # Настройка обработчиков OSC-сообщений
        self.setup_dispatcher()
        
    def setup_dispatcher(self) -> None:
        """Настройка обработчиков OSC-сообщений"""
        self.dispatcher.map(config.OSC_START_RECORDING, self.start_recording)
        self.dispatcher.map(config.OSC_STOP_RECORDING, self.stop_recording)
        self.dispatcher.map(config.OSC_SET_CAPTURE_NAME, self.set_capture_name)
        self.dispatcher.map(config.OSC_SET_CAPTURE_FOLDER, self.set_capture_folder)
        self.dispatcher.map(config.OSC_SET_CAPTURE_DESCRIPTION, self.set_capture_description)
        self.dispatcher.set_default_handler(self.default_handler)
    
    def start_recording(self, address: str, *args: Any) -> None:
        """
        Обработчик команды запуска записи
        
        Args:
            address: OSC-адрес сообщения
            *args: Аргументы OSC-сообщения
        """
        self.logger.info(f"Получена команда OSC: {address} -> Запуск записи")
        self.message_signal.emit(address, "Запуск записи")
        
        if self.shogun_worker and self.shogun_worker.connected:
            threading.Thread(target=self._run_async_task, 
                             args=(self.shogun_worker.startcapture,)).start()
        else:
            error_msg = "Не удалось запустить запись: нет подключения к Shogun Live"
            self.logger.warning(error_msg)
            self.send_osc_message(config.OSC_CAPTURE_ERROR, error_msg)
    
    def stop_recording(self, address: str, *args: Any) -> None:
        """
        Обработчик команды остановки записи
        
        Args:
            address: OSC-адрес сообщения
            *args: Аргументы OSC-сообщения
        """
        self.logger.info(f"Получена команда OSC: {address} -> Остановка записи")
        self.message_signal.emit(address, "Остановка записи")
        
        if self.shogun_worker and self.shogun_worker.connected:
            threading.Thread(target=self._run_async_task, 
                             args=(self.shogun_worker.stopcapture,)).start()
        else:
            error_msg = "Не удалось остановить запись: нет подключения к Shogun Live"
            self.logger.warning(error_msg)
            self.send_osc_message(config.OSC_CAPTURE_ERROR, error_msg)
    
    def set_capture_name(self, address: str, *args: Any) -> None:
        """
        Обработчик команды установки имени захвата
        
        Args:
            address: OSC-адрес сообщения
            *args: Аргументы OSC-сообщения (первый аргумент - новое имя)
        """
        if not args:
            error_msg = "Отсутствует имя захвата"
            self.logger.warning(f"Получена команда OSC: {address} -> {error_msg}")
            self.message_signal.emit(address, f"Ошибка: {error_msg}")
            self.send_osc_message(config.OSC_CAPTURE_ERROR, error_msg)
            return
            
        new_name = str(args[0])
        self.logger.info(f"Получена команда OSC: {address} -> Установка имени захвата: '{new_name}'")
        self.message_signal.emit(address, f"Установка имени захвата: '{new_name}'")
        
        if self.shogun_worker and self.shogun_worker.connected:
            async def set_name_task():
                return await self.shogun_worker.set_capture_name(new_name)
                
            threading.Thread(target=self._run_async_task, 
                             args=(set_name_task,)).start()
        else:
            error_msg = "Не удалось установить имя захвата: нет подключения к Shogun Live"
            self.logger.warning(error_msg)
            self.send_osc_message(config.OSC_CAPTURE_ERROR, error_msg)
    
    def set_capture_folder(self, address: str, *args: Any) -> None:
        """
        Обработчик команды установки папки захвата
        
        Args:
            address: OSC-адрес сообщения
            *args: Аргументы OSC-сообщения (первый аргумент - новая папка)
        """
        if not args:
            error_msg = "Отсутствует путь к папке захвата"
            self.logger.warning(f"Получена команда OSC: {address} -> {error_msg}")
            self.message_signal.emit(address, f"Ошибка: {error_msg}")
            self.send_osc_message(config.OSC_CAPTURE_ERROR, error_msg)
            return
            
        new_folder = str(args[0])
        self.logger.info(f"Получена команда OSC: {address} -> Установка папки захвата: '{new_folder}'")
        self.message_signal.emit(address, f"Установка папки захвата: '{new_folder}'")
        
        if self.shogun_worker and self.shogun_worker.connected:
            async def set_folder_task():
                return await self.shogun_worker.set_capture_folder(new_folder)
                
            threading.Thread(target=self._run_async_task, 
                             args=(set_folder_task,)).start()
        else:
            error_msg = "Не удалось установить папку захвата: нет подключения к Shogun Live"
            self.logger.warning(error_msg)
            self.send_osc_message(config.OSC_CAPTURE_ERROR, error_msg)
    
    def set_capture_description(self, address: str, *args: Any) -> None:
        """
        Обработчик команды установки описания захвата
        
        Args:
            address: OSC-адрес сообщения
            *args: Аргументы OSC-сообщения (первый аргумент - новое описание)
        """
        if not args:
            error_msg = "Отсутствует описание захвата"
            self.logger.warning(f"Получена команда OSC: {address} -> {error_msg}")
            self.message_signal.emit(address, f"Ошибка: {error_msg}")
            self.send_osc_message(config.OSC_CAPTURE_ERROR, error_msg)
            return
            
        new_description = str(args[0])
        self.logger.info(f"Получена команда OSC: {address} -> Установка описания захвата")
        self.message_signal.emit(address, "Установка описания захвата")
        
        if self.shogun_worker and self.shogun_worker.connected:
            async def set_description_task():
                return await self.shogun_worker.set_capture_description(new_description)
                
            threading.Thread(target=self._run_async_task, 
                             args=(set_description_task,)).start()
        else:
            error_msg = "Не удалось установить описание захвата: нет подключения к Shogun Live"
            self.logger.warning(error_msg)
            self.send_osc_message(config.OSC_CAPTURE_ERROR, error_msg)
    
    def default_handler(self, address: str, *args: Any) -> None:
        """
        Обработчик для неизвестных OSC-сообщений
        
        Args:
            address: OSC-адрес сообщения
            *args: Аргументы OSC-сообщения
        """
        args_str = ", ".join(str(arg) for arg in args) if args else "нет аргументов"
        self.logger.debug(f"Получено неизвестное OSC-сообщение: {address} -> {args_str}")
        self.message_signal.emit(address, args_str)
    
    def _run_async_task(self, coro_func: Callable) -> Any:
        """
        Запускает асинхронную функцию в отдельном цикле событий
        
        Args:
            coro_func: Асинхронная функция для выполнения
            
        Returns:
            Any: Результат выполнения функции
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro_func())
        finally:
            loop.close()
    
    def send_osc_message(self, address: str, value: Any) -> bool:
        """
        Отправляет OSC-сообщение
        
        Args:
            address: OSC-адрес сообщения
            value: Значение для отправки
            
        Returns:
            bool: True если сообщение отправлено успешно, иначе False
        """
        try:
            # Создаем клиент для отправки, если еще не создан
            if not self.osc_client:
                # Используем настройки из конфигурации
                target_ip = config.app_settings.get("osc_broadcast_ip", config.DEFAULT_OSC_BROADCAST_IP)
                target_port = config.app_settings.get("osc_broadcast_port", config.DEFAULT_OSC_BROADCAST_PORT)
                
                # Создаем клиент с обычным сокетом вместо широковещательного
                # для избежания ошибок доступа
                if target_ip == "255.255.255.255":
                    # Создаем собственный сокет с поддержкой широковещательных сообщений
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    # Привязываем к любому доступному порту
                    sock.bind(('', 0))
                    # Создаем клиент с нашим сокетом
                    self.osc_client = udp_client.SimpleUDPClient(target_ip, target_port, sock)
                else:
                    # Для обычного IP используем стандартный клиент
                    self.osc_client = udp_client.SimpleUDPClient(target_ip, target_port)
                
                self.logger.info(f"Создан OSC-клиент для отправки сообщений на {target_ip}:{target_port}")
                
            # Отправляем сообщение
            self.osc_client.send_message(address, value)
            self.logger.debug(f"Отправлено OSC-сообщение: {address} -> {value}")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка отправки OSC-сообщения: {e}")
            return False
    
    def run(self) -> None:
        """Запуск OSC-сервера"""
        try:
            self.logger.info(f"Запуск OSC-сервера на {self.ip}:{self.port}")
            
            # Создаем сервер с обработкой ошибок
            try:
                self.server = osc_server.ThreadingOSCUDPServer((self.ip, self.port), self.dispatcher)
                self._socket = self.server.socket
            except socket.error as e:
                self.logger.error(f"Не удалось создать OSC-сервер: {e}")
                # Сигнализируем об ошибке
                self.message_signal.emit("ERROR", f"Не удалось запустить OSC-сервер: {e}")
                return
            
            # Устанавливаем таймаут для сокета, чтобы можно было корректно остановить сервер
            self._socket.settimeout(0.5)
            
            # Запускаем сервер с возможностью остановки
            while self.running:
                try:
                    self.server.handle_request()
                except socket.timeout:
                    # Таймаут сокета - нормальная ситуация, продолжаем работу
                    continue
                except Exception as e:
                    if self.running:  # Логируем ошибку только если сервер должен работать
                        self.logger.error(f"Ошибка при обработке OSC-запроса: {e}")
        except Exception as e:
            self.logger.error(f"Критическая ошибка OSC-сервера: {e}")
    
    def stop(self) -> None:
        """Остановка OSC-сервера"""
        self.running = False
        # Закрываем сервер если он создан
        if self.server:
            try:
                self.server.server_close()
            except Exception as e:
                self.logger.error(f"Ошибка при закрытии OSC-сервера: {e}")
        
        # Закрываем клиент для отправки сообщений
        if self.osc_client and hasattr(self.osc_client, '_sock'):
            try:
                self.osc_client._sock.close()
            except Exception as e:
                self.logger.error(f"Ошибка при закрытии OSC-клиента: {e}")
                
        self.logger.info("OSC-сервер остановлен")

def format_osc_message(address: str, value: Any, with_timestamp: bool = True) -> str:
    """
    Форматирует OSC-сообщение для отображения
    
    Args:
        address: OSC-адрес сообщения
        value: Значение сообщения
        with_timestamp: Добавлять ли временную метку
        
    Returns:
        str: Отформатированное сообщение
    """
    if with_timestamp:
        timestamp = datetime.now().strftime("%H:%M:%S")
        return f"<b>[{timestamp}]</b> {address} → {value}"
    else:
        return f"{address} → {value}"