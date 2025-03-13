"""
Модуль для взаимодействия с Shogun Live API.
Предоставляет функциональность подключения, мониторинга и управления записью.
"""

import asyncio
import logging
import time
import psutil
from typing import Optional, Tuple, Union, Any, Dict
from PyQt5.QtCore import QThread, pyqtSignal

from vicon_core_api import Client, Result
from shogun_live_api import CaptureServices
import config

class ShogunWorker(QThread):
    """Рабочий поток для взаимодействия с Shogun Live"""
    connection_signal = pyqtSignal(bool)  # Сигнал состояния подключения
    status_signal = pyqtSignal(str)       # Сигнал статуса
    recording_signal = pyqtSignal(bool)   # Сигнал состояния записи
    capture_name_changed_signal = pyqtSignal(str)  # Сигнал изменения имени захвата
    capture_folder_changed_signal = pyqtSignal(str)  # Сигнал изменения директории захвата
    capture_error_signal = pyqtSignal(str)  # Сигнал об ошибке записи
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger('ShogunOSC')
        self.running = True
        self.connected = False
        self.shogun_client = None
        self.capture = None
        self.shogun_pid = None
        self.loop = None
        self._last_check_time = 0  # Для оптимизации частоты проверок
        self._check_interval = 1.0  # Интервал проверки в секундах
        self._current_capture_name = ""  # Текущее имя захвата для отслеживания изменений
        self._current_capture_folder = ""  # Текущая директория захвата
        self._current_capture_description = ""  # Текущее описание захвата
        
    def run(self):
        """Основной метод потока"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Первая попытка подключения
        self.connected = self.loop.run_until_complete(self.connect_shogun())
        self.connection_signal.emit(self.connected)
        
        # Основной цикл мониторинга
        while self.running:
            try:
                current_time = time.time()
                # Оптимизация: проверяем только через определенные интервалы
                if current_time - self._last_check_time >= self._check_interval:
                    self._last_check_time = current_time
                    
                    # Проверяем наличие процесса Shogun Live
                    shogun_running = self.check_shogun_process()
                    
                    # Проверяем соединение, если процесс запущен
                    if shogun_running:
                        if not self.connected:
                            self.logger.info("Shogun Live обнаружен. Выполняем подключение...")
                            self.connected = self.loop.run_until_complete(self.connect_shogun())
                            self.connection_signal.emit(self.connected)
                        else:
                            # Проверяем существующее соединение
                            connection_ok = self.loop.run_until_complete(self.ensure_connection())
                            if not connection_ok:
                                self.logger.warning("Соединение с Shogun Live потеряно")
                                self.connected = False
                                self.connection_signal.emit(False)
                            
                            # Если подключены, обновляем статус записи
                            if self.connected:
                                is_recording = self.loop.run_until_complete(self.check_shogun())
                                self.recording_signal.emit(is_recording)
                                
                                # Проверяем изменение имени захвата и папки захвата
                                self.loop.run_until_complete(self._check_capture_settings_change())
                    else:
                        if self.connected:
                            self.logger.warning("Shogun Live не обнаружен. Соединение потеряно.")
                            self.connected = False
                            self.connection_signal.emit(False)
                            self.recording_signal.emit(False)
                    
                    # Обновляем статус в интерфейсе
                    status = config.STATUS_CONNECTED if self.connected else config.STATUS_DISCONNECTED
                    self.status_signal.emit(status)
                
                # Короткая пауза для снижения нагрузки на CPU
                time.sleep(0.1)
            except Exception as e:
                self.logger.error(f"Ошибка в основном цикле мониторинга: {e}")
                # Продолжаем работу после ошибки
                time.sleep(1)
    
    async def _check_capture_settings_change(self) -> None:
        """Проверяет изменение настроек захвата в Shogun Live"""
        try:
            if not self.capture:
                return
                
            # Получаем текущее имя захвата
            result, capture_name = self.capture.capture_name()
            
            # Проверяем успешность запроса
            if not result:
                self.logger.debug(f"Не удалось получить имя захвата: {result}")
                return
                
            # Если имя изменилось, отправляем сигнал
            if capture_name != self._current_capture_name:
                self.logger.info(f"Имя захвата изменилось: '{self._current_capture_name}' -> '{capture_name}'")
                self._current_capture_name = capture_name
                self.capture_name_changed_signal.emit(capture_name)
            
            # Получаем текущую папку захвата
            result, capture_folder = self.capture.capture_folder()
            
            # Проверяем успешность запроса
            if not result:
                self.logger.debug(f"Не удалось получить папку захвата: {result}")
                return
                
            # Если папка изменилась, отправляем сигнал
            if capture_folder != self._current_capture_folder:
                self.logger.info(f"Папка захвата изменилась: '{self._current_capture_folder}' -> '{capture_folder}'")
                self._current_capture_folder = capture_folder
                self.capture_folder_changed_signal.emit(capture_folder)
                
        except Exception as e:
            self.logger.debug(f"Ошибка при проверке настроек захвата: {e}")
    
    def check_shogun_process(self) -> bool:
        """
        Проверяет, запущен ли процесс Shogun Live и изменился ли его PID
        
        Returns:
            bool: True если процесс Shogun Live запущен, иначе False
        """
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                proc_name = proc.info['name']
                if proc_name and ('ShogunLive' in proc_name or 'Shogun Live' in proc_name):
                    pid = proc.info['pid']
                    # Если PID изменился, считаем что Shogun перезапущен
                    if self.shogun_pid and self.shogun_pid != pid:
                        self.logger.info(f"Обнаружен перезапуск Shogun Live (PID: {self.shogun_pid} -> {pid})")
                        self.shogun_pid = pid
                        self.connected = False  # Сбрасываем подключение
                        return True
                    self.shogun_pid = pid
                    return True
            return False
        except Exception as e:
            self.logger.debug(f"Ошибка проверки процесса Shogun: {e}")
            return False
    
    async def connect_shogun(self) -> bool:
        """
        Подключение к Shogun Live
        
        Returns:
            bool: True если подключение успешно, иначе False
        """
        try:
            self.logger.info("Подключение к Shogun Live...")
            # Добавляем таймаут для операции подключения
            self.shogun_client = Client('localhost')
            self.capture = CaptureServices(self.shogun_client)
            
            # Проверяем, что соединение действительно работает
            if not await self._test_connection():
                self.logger.warning("Соединение установлено, но API не отвечает")
                return False
            
            # Получаем текущие настройки захвата при подключении
            try:
                # Имя захвата
                result, capture_name = self.capture.capture_name()
                if result:
                    self._current_capture_name = capture_name
                    self.logger.info(f"Текущее имя захвата: '{capture_name}'")
                    
                # Папка захвата
                result, capture_folder = self.capture.capture_folder()
                if result:
                    self._current_capture_folder = capture_folder
                    self.logger.info(f"Текущая папка захвата: '{capture_folder}'")
                    self.capture_folder_changed_signal.emit(capture_folder)
            except Exception as e:
                self.logger.debug(f"Не удалось получить настройки захвата при подключении: {e}")
                
            self.logger.info("Подключено к Shogun Live")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка подключения к Shogun Live: {e}")
            return False
    
    async def _test_connection(self) -> bool:
        """
        Проверяет, что соединение с Shogun Live работает
        
        Returns:
            bool: True если соединение работает, иначе False
        """
        try:
            # Выполняем простой запрос для проверки соединения
            _ = str(self.capture.latest_capture_state())
            return True
        except Exception as e:
            self.logger.debug(f"Тест соединения не пройден: {e}")
            return False
    
    async def ensure_connection(self) -> bool:
        """
        Проверка соединения и переподключение при необходимости
        
        Returns:
            bool: True если соединение активно, иначе False
        """
        if not self.shogun_client or not self.capture:
            return await self.connect_shogun()
        
        try:
            # Простая проверка - пытаемся выполнить запрос к API
            status = str(self.capture.latest_capture_state())
            return True
        except Exception as e:
            self.logger.debug(f"Ошибка проверки соединения: {e}")
            return await self.reconnect_shogun()
    
    async def reconnect_shogun(self) -> bool:
        """
        Переподключение к Shogun Live с экспоненциальной отсрочкой
        
        Returns:
            bool: True если переподключение успешно, иначе False
        """
        self.logger.info("Попытка переподключения к Shogun Live...")
        
        # Закрываем существующее соединение если оно есть
        if self.shogun_client:
            try:
                # Закрытие клиентского соединения если есть такой метод
                if hasattr(self.shogun_client, 'disconnect'):
                    self.shogun_client.disconnect()
                elif hasattr(self.shogun_client, 'close'):
                    self.shogun_client.close()
            except Exception as e:
                self.logger.debug(f"Ошибка при закрытии соединения: {e}")
        
        # Пытаемся переподключиться с экспоненциальной отсрочкой
        attempt = 0
        max_attempts = config.MAX_RECONNECT_ATTEMPTS
        base_delay = config.BASE_RECONNECT_DELAY
        
        while attempt < max_attempts and self.running:  # Проверяем self.running для возможности прервать
            result = await self.connect_shogun()
            if result:
                self.recording_signal.emit(await self.check_shogun())
                return True
            
            attempt += 1
            # Экспоненциальная отсрочка с максимальным значением
            delay = min(base_delay * (1.5 ** (attempt - 1)), config.MAX_RECONNECT_DELAY)
            self.logger.debug(f"Попытка {attempt} не удалась. Следующая через {delay:.1f} секунд...")
            
            # Разбиваем ожидание на короткие интервалы для возможности прерывания
            for _ in range(int(delay * 10)):
                if not self.running:
                    return False
                await asyncio.sleep(0.1)
        
        self.logger.error(f"Не удалось переподключиться к Shogun Live после {max_attempts} попыток")
        return False
    
    async def check_shogun(self) -> bool:
        """
        Проверка состояния записи
        
        Returns:
            bool: True если запись активна, иначе False
        """
        try:
            if not self.capture:
                return False
                
            status = str(self.capture.latest_capture_state())
            is_recording = 'Started' in status
            return is_recording
        except Exception as e:
            self.logger.debug(f"Ошибка проверки состояния Shogun Live: {e}")
            return False
    
    async def startcapture(self) -> Optional[Union[str, Dict]]:
        """
        Запуск записи
        
        Returns:
            Optional[Union[str, Dict]]: Информация о записи если успешно, иначе None
        """
        try:
            # Проверяем соединение перед операцией
            if not await self.ensure_connection():
                error_msg = "Не удалось установить соединение с Shogun Live"
                self.logger.error(error_msg)
                self.capture_error_signal.emit(error_msg)
                return None
            
            # Проверяем, не идет ли уже запись
            if await self.check_shogun():
                self.logger.info("Запись уже активна в Shogun Live")
                return {"status": "already_recording"}
                
            # Запускаем запись
            result = self.capture.start_capture()
            
            # Проверяем результат запуска записи
            if not result:
                error_msg = "Shogun Live отклонил запрос на запись"
                self.logger.error(error_msg)
                self.capture_error_signal.emit(error_msg)
                return None
                
            self.logger.info("Запись начата в Shogun Live")
            return {"status": "started"}
            
        except Exception as e:
            error_msg = f"Ошибка запуска записи: {e}"
            self.logger.error(error_msg)
            self.capture_error_signal.emit(error_msg)
            
            # Пробуем переподключиться и повторить операцию
            if await self.reconnect_shogun():
                try:
                    result = self.capture.start_capture()
                    if not result:
                        error_msg = "Shogun Live отклонил запрос на запись после переподключения"
                        self.logger.error(error_msg)
                        self.capture_error_signal.emit(error_msg)
                        return None
                        
                    self.logger.info("Запись начата в Shogun Live после переподключения")
                    return {"status": "started_after_reconnect"}
                except Exception as e2:
                    error_msg = f"Не удалось запустить запись после переподключения: {e2}"
                    self.logger.error(error_msg)
                    self.capture_error_signal.emit(error_msg)
            return None
    
    async def stopcapture(self) -> bool:
        """
        Остановка записи
        
        Returns:
            bool: True если запись успешно остановлена, иначе False
        """
        try:
            # Проверяем соединение перед операцией
            if not await self.ensure_connection():
                error_msg = "Не удалось установить соединение с Shogun Live"
                self.logger.error(error_msg)
                self.capture_error_signal.emit(error_msg)
                return False
            
            # Проверяем, идет ли запись
            if not await self.check_shogun():
                self.logger.info("Запись не активна в Shogun Live")
                return True
                
            result = self.capture.stop_capture(0)
            if not result:
                error_msg = "Shogun Live отклонил запрос на остановку записи"
                self.logger.error(error_msg)
                self.capture_error_signal.emit(error_msg)
                return False
                
            self.logger.info("Запись остановлена в Shogun Live")
            return True
        except Exception as e:
            error_msg = f"Ошибка остановки записи: {e}"
            self.logger.error(error_msg)
            self.capture_error_signal.emit(error_msg)
            
            # Пробуем переподключиться и повторить операцию
            if await self.reconnect_shogun():
                try:
                    result = self.capture.stop_capture(0)
                    if not result:
                        error_msg = "Shogun Live отклонил запрос на остановку записи после переподключения"
                        self.logger.error(error_msg)
                        self.capture_error_signal.emit(error_msg)
                        return False
                        
                    self.logger.info("Запись остановлена в Shogun Live после переподключения")
                    return True
                except Exception as e2:
                    error_msg = f"Не удалось остановить запись после переподключения: {e2}"
                    self.logger.error(error_msg)
                    self.capture_error_signal.emit(error_msg)
            return False
    
    async def set_capture_name(self, name: str) -> bool:
        """
        Устанавливает имя захвата в Shogun Live
        
        Args:
            name: Новое имя захвата
            
        Returns:
            bool: True если имя успешно установлено, иначе False
        """
        try:
            if not self.capture:
                error_msg = "Нет соединения с Shogun Live"
                self.logger.error(error_msg)
                return False
                
            result = self.capture.set_capture_name(name)
            if result:
                self.logger.info(f"Имя захвата установлено: '{name}'")
                self._current_capture_name = name
                return True
            else:
                error_msg = f"Не удалось установить имя захвата: {result}"
                self.logger.error(error_msg)
                return False
        except Exception as e:
            self.logger.error(f"Ошибка при установке имени захвата: {e}")
            return False
    
    async def set_capture_folder(self, folder: str) -> bool:
        """
        Устанавливает папку захвата в Shogun Live
        
        Args:
            folder: Новая папка захвата
            
        Returns:
            bool: True если папка успешно установлена, иначе False
        """
        try:
            if not self.capture:
                error_msg = "Нет соединения с Shogun Live"
                self.logger.error(error_msg)
                return False
                
            result = self.capture.set_capture_folder(folder)
            if result:
                self.logger.info(f"Папка захвата установлена: '{folder}'")
                self._current_capture_folder = folder
                return True
            else:
                error_msg = f"Не удалось установить папку захвата: {result}"
                self.logger.error(error_msg)
                return False
        except Exception as e:
            self.logger.error(f"Ошибка при установке папки захвата: {e}")
            return False
    
    async def set_capture_description(self, description: str) -> bool:
        """
        Устанавливает описание захвата в Shogun Live
        
        Args:
            description: Новое описание захвата
            
        Returns:
            bool: True если описание успешно установлено, иначе False
        """
        try:
            if not self.capture:
                error_msg = "Нет соединения с Shogun Live"
                self.logger.error(error_msg)
                return False
            
            # Проверяем, есть ли метод для установки описания (может отсутствовать в некоторых версиях API)
            if hasattr(self.capture, 'set_capture_description'):
                result = self.capture.set_capture_description(description)
                if result:
                    self.logger.info(f"Описание захвата установлено")
                    self._current_capture_description = description
                    return True
                else:
                    error_msg = f"Не удалось установить описание захвата: {result}"
                    self.logger.error(error_msg)
                    return False
            else:
                self.logger.warning("API Shogun Live не поддерживает установку описания захвата")
                return False
        except Exception as e:
            self.logger.error(f"Ошибка при установке описания захвата: {e}")
            return False
    
    def stop(self):
        """Остановка рабочего потока"""
        self.running = False
        # Закрываем соединение при остановке
        if self.shogun_client:
            try:
                if hasattr(self.shogun_client, 'disconnect'):
                    self.shogun_client.disconnect()
                elif hasattr(self.shogun_client, 'close'):
                    self.shogun_client.close()
            except Exception as e:
                self.logger.debug(f"Ошибка при закрытии соединения: {e}")
