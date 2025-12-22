#!/usr/bin/env python3
"""
Модуль для синхронизации данных из Bitrix (файлы 1С)
Скачивает XML файлы и конвертирует их в JSON
"""

import requests
from bs4 import BeautifulSoup
import os
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BitrixSyncClient:
    """Клиент для синхронизации данных из Bitrix"""
    
    def __init__(self, base_url: str, login: str, password: str):
        """
        Инициализация клиента
        
        Args:
            base_url: Базовый URL сайта (например, https://student.planetenglish.ru)
            login: Логин для входа
            password: Пароль
        """
        self.base_url = base_url
        self.login = login
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def authenticate(self) -> bool:
        """
        Авторизация на сайте
        
        Returns:
            True если успешно, False если ошибка
        """
        try:
            # Формируем URL для авторизации
            login_url = f"{self.base_url}/bitrix/admin/index.php"
            files_url = f"{self.base_url}/bitrix/admin/fileman_admin.php?lang=ru&site=s1&path=/upload/1c_exchange"
            
            # Получаем страницу входа
            response = self.session.get(login_url, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"Не удалось получить страницу входа: {response.status_code}")
                return False
            
            # Парсим форму
            soup = BeautifulSoup(response.text, 'html.parser')
            login_form = soup.find('form', attrs={'name': 'form_auth'})
            
            if not login_form:
                logger.error("Форма авторизации не найдена")
                return False
            
            # Собираем поля формы
            form_data = {}
            for input_field in login_form.find_all('input'):
                name = input_field.get('name')
                value = input_field.get('value', '')
                if name:
                    form_data[name] = value
            
            # Добавляем учетные данные
            form_data['TYPE'] = 'AUTH'
            form_data['USER_LOGIN'] = self.login
            form_data['USER_PASSWORD'] = self.password
            form_data['Login'] = 'Y'
            
            # Отправляем форму
            auth_url = f"{files_url}&login=yes"
            auth_response = self.session.post(auth_url, data=form_data, timeout=10, allow_redirects=True)
            
            # Проверяем успешность
            if 'USER_LOGIN' not in auth_response.text or 'fileman' in auth_response.url:
                logger.info("Авторизация успешна")
                return True
            else:
                logger.error("Авторизация не удалась")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при авторизации: {e}")
            return False
    
    def download_file(self, file_type: str, save_path: str) -> Optional[str]:
        """
        Скачивание файла по типу
        
        Args:
            file_type: Тип файла ('clients', 'contracts', 'transactions')
            save_path: Путь для сохранения файла
            
        Returns:
            Путь к сохраненному файлу или None если ошибка
        """
        # Маппинг типов файлов на URL
        file_urls = {
            'clients': f"{self.base_url}/upload/1c_exchange/clients/clients.xml",
            'contracts': f"{self.base_url}/upload/1c_exchange/contracts/contracts.xml",
            'transactions': f"{self.base_url}/upload/1c_exchange/tranzactions/transactions.xml"
        }
        
        if file_type not in file_urls:
            logger.error(f"Неизвестный тип файла: {file_type}")
            return None
        
        url = file_urls[file_type]
        
        try:
            logger.info(f"Скачивание {file_type}.xml...")
            response = self.session.get(url, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"Ошибка скачивания {file_type}: HTTP {response.status_code}")
                return None
            
            # Создаем директорию если не существует
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            # Сохраняем файл
            with open(save_path, 'wb') as f:
                f.write(response.content)
            
            logger.info(f"Сохранено: {save_path} ({len(response.content)} байт)")
            return save_path
            
        except Exception as e:
            logger.error(f"Ошибка при скачивании файла {file_type}: {e}")
            return None
    
    def xml_to_json(self, xml_path: str, json_path: str, file_type: str) -> bool:
        """
        Конвертация XML в JSON
        
        Args:
            xml_path: Путь к XML файлу
            json_path: Путь для сохранения JSON
            file_type: Тип файла для правильного парсинга
            
        Returns:
            True если успешно, False если ошибка
        """
        try:
            logger.info(f"Конвертация {file_type}.xml -> JSON...")
            
            # Парсим XML
            tree = ET.parse(xml_path)
            root = tree.getroot()
            
            # Определяем namespace
            ns = {'ns': 'urn:1C.ru:commerceml_2'}
            
            # Конвертируем в зависимости от типа
            if file_type == 'clients':
                data = self._parse_clients(root, ns)
            elif file_type == 'contracts':
                data = self._parse_contracts(root, ns)
            elif file_type == 'transactions':
                data = self._parse_transactions(root, ns)
            else:
                logger.error(f"Неизвестный тип для конвертации: {file_type}")
                return False
            
            # Сохраняем JSON
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Сохранено: {json_path} ({len(data.get('items', []))} записей)")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при конвертации {file_type}: {e}")
            return False
    
    def _parse_clients(self, root, ns) -> Dict:
        """Парсинг файла clients.xml"""
        clients = []
        
        for client in root.findall('.//ns:Контрагент', ns):
            client_data = {
                'id': self._get_text(client, 'ns:Ид', ns),
                'login': self._get_text(client, 'ns:Логин', ns),
                'student': {
                    'last_name': self._get_text(client, './/ns:Фамилия', ns),
                    'first_name': self._get_text(client, './/ns:Имя', ns),
                    'middle_name': self._get_text(client, './/ns:Отчество', ns),
                    'account': self._get_text(client, './/ns:ЛицевойСчет', ns),
                    'branch': self._get_text(client, './/ns:Филиал', ns),
                    'group': self._get_text(client, './/ns:Группа', ns),
                    'program': self._get_text(client, './/ns:ОсновнаяПрограмма', ns),
                    'teacher': self._get_text(client, './/ns:Преподаватель', ns),
                    'bonus': self._get_text(client, './/ns:Бонус', ns),
                },
                'contacts': {
                    'contact_person': self._get_text(client, './/ns:КонтактноеЛицо', ns),
                    'phone': self._get_text(client, './/ns:ТелефонДляСвязи', ns),
                    'email': self._get_text(client, './/ns:ЭлектроннаяПочтаДляУведомлений', ns),
                }
            }
            clients.append(client_data)
        
        return {
            'updated_at': datetime.now().isoformat(),
            'count': len(clients),
            'items': clients
        }
    
    def _parse_contracts(self, root, ns) -> Dict:
        """Парсинг файла contracts.xml"""
        contracts = []
        
        for contract in root.findall('.//ns:Контракт', ns):
            contract_data = {
                'id': self._get_text(contract, 'ns:Ид', ns),
                'name': self._get_text(contract, 'ns:Название', ns),
                'balance': self._get_text(contract, 'ns:Баланс', ns),
                'bonuses': self._get_text(contract, 'ns:Бонусы', ns),
                'client_id': self._get_text(contract, 'ns:ИдКонтрагента', ns),
            }
            contracts.append(contract_data)
        
        return {
            'updated_at': datetime.now().isoformat(),
            'count': len(contracts),
            'items': contracts
        }
    
    def _parse_transactions(self, root, ns) -> Dict:
        """Парсинг файла transactions.xml"""
        transactions = []
        
        for trans in root.findall('.//ns:Транзакция', ns):
            trans_data = {
                'id': self._get_text(trans, 'ns:Ид', ns),
                'date': self._get_text(trans, 'ns:Дата', ns),
                'amount': self._get_text(trans, 'ns:Сумма', ns),
                'description': self._get_text(trans, 'ns:Описание', ns),
                'contract_id': self._get_text(trans, 'ns:ИдКонтракта', ns),
            }
            transactions.append(trans_data)
        
        return {
            'updated_at': datetime.now().isoformat(),
            'count': len(transactions),
            'items': transactions
        }
    
    def _get_text(self, element, path: str, ns) -> str:
        """Безопасное извлечение текста из XML элемента"""
        found = element.find(path, ns)
        return found.text.strip() if found is not None and found.text else ''
    
    def sync_file(self, file_type: str, data_dir: str = 'data') -> bool:
        """
        Полная синхронизация файла: скачивание + конвертация в JSON
        
        Args:
            file_type: Тип файла ('clients', 'contracts', 'transactions')
            data_dir: Директория для сохранения данных
            
        Returns:
            True если успешно, False если ошибка
        """
        # Пути для сохранения
        xml_path = os.path.join(data_dir, 'xml', f'{file_type}.xml')
        json_path = os.path.join(data_dir, f'{file_type}.json')
        
        # Скачиваем XML
        if not self.download_file(file_type, xml_path):
            return False
        
        # Конвертируем в JSON
        if not self.xml_to_json(xml_path, json_path, file_type):
            return False
        
        return True


def main():
    """Пример использования"""
    # Настройки (в production используйте переменные окружения)
    BASE_URL = "https://student.planetenglish.ru"
    LOGIN = "konstantin@planetenglish.ru"
    PASSWORD = "Fv%8D3_(5Wp"
    
    # Создаем клиент
    client = BitrixSyncClient(BASE_URL, LOGIN, PASSWORD)
    
    # Авторизуемся
    if not client.authenticate():
        logger.error("Не удалось авторизоваться")
        return
    
    # Синхронизируем все файлы
    files = ['clients', 'contracts', 'transactions']
    
    for file_type in files:
        logger.info(f"\n{'='*60}")
        logger.info(f"Синхронизация {file_type}...")
        logger.info(f"{'='*60}")
        
        if client.sync_file(file_type):
            logger.info(f"✅ {file_type} - успешно синхронизирован")
        else:
            logger.error(f"❌ {file_type} - ошибка синхронизации")


if __name__ == "__main__":
    main()
