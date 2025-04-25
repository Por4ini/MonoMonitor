import sqlite3
import json
import os
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
import time
import logging
import logging.handlers
import colorlog
from dotenv import load_dotenv
from pathlib import Path

# Завантаження змінних середовища з .env файлу
load_dotenv()

# Створюємо константу для Київського часового поясу (UTC+3)
KYIV_TZ = timezone(timedelta(hours=3))

# Налаштування кольорових логів
def setup_logging():
    # Створюємо папку для логів, якщо її не існує
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Створюємо форматтер з кольорами для консолі
    console_formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(levelname)s - %(message)s",
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )
    
    # Форматтер для файлових логів (без кольорів)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Обробник для консолі
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    
    # Обробник для файлів з ротацією за датою
    today = datetime.now(KYIV_TZ).strftime('%Y-%m-%d')
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=f"logs/monobank_{today}.log",
        when='midnight',
        interval=1,
        backupCount=30,  # Зберігаємо логи за 30 днів
        encoding='utf-8'
    )
    file_handler.setFormatter(file_formatter)
    
    # Налаштування корневого логгера
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Повертаємо наш логгер
    logger = logging.getLogger('monobank_monitor')
    return logger

# Отримуємо налаштування з .env файлу
def get_settings():
    return {
        # Monobank API
        "token": os.getenv("MONO_API_TOKEN", "uiB-kwhXL_tmxdQFbvhtp8AQ3uzqq_o8fbMOJNXqqfLo"),
        "api_base_url": os.getenv("MONO_API_BASE_URL", "https://api.monobank.ua"),
        
        # Налаштування SMTP
        "smtp_server": os.getenv("SMTP_SERVER", ""),
        "smtp_port": int(os.getenv("SMTP_PORT", "")),
        "smtp_username": os.getenv("SMTP_USERNAME", ""),
        "smtp_password": os.getenv("SMTP_PASSWORD", ""),
        "smtp_sender": os.getenv("SMTP_SENDER", ""),
        "smtp_recipients": os.getenv("SMTP_RECIPIENTS", "").split(','),
        
        # Інші налаштування
        "days_to_fetch": int(os.getenv("DAYS_TO_FETCH", "2")),
        "api_delay": int(os.getenv("API_DELAY", "61")),
        "db_file": os.getenv("DB_FILE", "monobank_data.db"),
        
        # Фільтри
        "ignore_senders": os.getenv("IGNORE_SENDERS", "").split(','),
    }

def create_db(db_file):
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    
    # Таблиця клієнтів
    c.execute('''
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        name TEXT,
        webhook_url TEXT,
        permissions TEXT,
        data_json TEXT,
        updated_at TEXT
    )
    ''')
    
    # Таблиця рахунків
    c.execute('''
    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        client_id TEXT,
        send_id TEXT,
        balance INTEGER,
        credit_limit INTEGER,
        type TEXT,
        currency_code INTEGER,
        iban TEXT,
        updated_at TEXT,
        FOREIGN KEY (client_id) REFERENCES clients (client_id)
    )
    ''')
    
    # Таблиця транзакцій з полем processed
    c.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id TEXT PRIMARY KEY,
        account_id TEXT,
        time INTEGER,
        description TEXT,
        mcc INTEGER,
        amount INTEGER,
        operation_amount INTEGER,
        currency_code INTEGER,
        balance INTEGER,
        counter_name TEXT,
        comment TEXT,
        created_at TEXT,
        processed BOOLEAN DEFAULT 0,
        FOREIGN KEY (account_id) REFERENCES accounts (id)
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("База даних ініціалізована або підтверджена")

def get_client_info(token, api_base_url):
    logger.info("Отримання інформації про клієнта з API")
    url = f'{api_base_url}/personal/client-info'
    headers = {'X-Token': token}
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        logger.error(f"Помилка API: {response.status_code}, {response.text}")
        raise Exception(f"API error: {response.status_code}, {response.text}")
    
    client_data = response.json()
    logger.info(f"Отримано дані клієнта: {client_data.get('name', 'Невідомий')}")
    logger.info(f"Знайдено {len(client_data.get('accounts', []))} рахунків")
    return client_data

def save_client_info(client_data, db_file):
    logger.info("Збереження даних клієнта в базу")
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    
    now = datetime.now(KYIV_TZ).isoformat()
    
    # Зберігаємо клієнта
    c.execute(
        "INSERT OR REPLACE INTO clients VALUES (?, ?, ?, ?, ?, ?)",
        (
            client_data.get('clientId', ''),
            client_data.get('name', ''),
            client_data.get('webHookUrl', ''),
            client_data.get('permissions', ''),
            json.dumps(client_data),
            now
        )
    )
    
    # Зберігаємо рахунки
    for account in client_data.get('accounts', []):
        c.execute(
            "INSERT OR REPLACE INTO accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                account.get('id', ''),
                client_data.get('clientId', ''),
                account.get('sendId', ''),
                account.get('balance', 0),
                account.get('creditLimit', 0),
                account.get('type', ''),
                account.get('currencyCode', 0),
                account.get('iban', ''),
                now
            )
        )
        logger.info(f"Збережено рахунок {account.get('id', '')}, тип: {account.get('type', '')}")
    
    conn.commit()
    conn.close()
    logger.info("Дані клієнта збережено в базу")

def get_statements(token, api_base_url, account_id, days=7):
    """Отримати виписки за вказаний період"""
    # Використовуємо київський час
    now = datetime.now(KYIV_TZ)
    now_ts = int(now.timestamp())
    days_ago_ts = int((now - timedelta(days=days)).timestamp())
    
    logger.info(f"Отримання виписки для рахунку {account_id} з {datetime.fromtimestamp(days_ago_ts, KYIV_TZ).strftime('%d.%m.%Y %H:%M')} по {datetime.fromtimestamp(now_ts, KYIV_TZ).strftime('%d.%m.%Y %H:%M')}")
    
    url = f'{api_base_url}/personal/statement/{account_id}/{days_ago_ts}/{now_ts}'
    headers = {'X-Token': token}
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        logger.error(f"Помилка API при отриманні виписки: {response.status_code}, {response.text}")
        raise Exception(f"API error: {response.status_code}, {response.text}")
    
    statements = response.json()
    logger.info(f"Отримано {len(statements)} транзакцій для рахунку {account_id}")
    
    # Логуємо деталі кожної транзакції
    for idx, tx in enumerate(statements):
        tx_time = datetime.fromtimestamp(tx.get('time', 0), KYIV_TZ).strftime('%d.%m.%Y %H:%M')
        amount = tx.get('amount', 0) / 100
        description = tx.get('description', '')[:30]
        logger.info(f"Транзакція {idx+1}/{len(statements)}: {tx_time}, {amount:.2f} грн, '{description}...'")
    
    return statements

def save_transaction(account_id, transaction, db_file):
    """Зберігаємо одну транзакцію і повертаємо чи вона нова"""
    tx_id = transaction.get('id', '')
    amount = transaction.get('amount', 0) / 100
    description = transaction.get('description', '')[:30]
    
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    
    now = datetime.now(KYIV_TZ).isoformat()
    is_new = False
    
    # Перевіряємо чи існує транзакція
    c.execute("SELECT processed FROM transactions WHERE id = ?", (tx_id,))
    result = c.fetchone()
    
    if not result:
        # Нова транзакція
        c.execute(
            "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tx_id,
                account_id,
                transaction.get('time', 0),
                transaction.get('description', ''),
                transaction.get('mcc', 0),
                transaction.get('amount', 0),
                transaction.get('operationAmount', 0),
                transaction.get('currencyCode', 0),
                transaction.get('balance', 0),
                transaction.get('counterName', ''),
                transaction.get('comment', ''),
                now,
                False  # Нова транзакція, не відправлена
            )
        )
        logger.info(f"Додано нову транзакцію: {tx_id}, {amount:.2f} грн, '{description}...'")
        is_new = True
    elif result[0] == 0:
        # Існуюча транзакція, але ще не оброблена
        logger.info(f"Знайдено необроблену транзакцію: {tx_id}, {amount:.2f} грн, '{description}...'")
        is_new = True
    else:
        logger.info(f"Транзакція вже оброблена: {tx_id}, {amount:.2f} грн, '{description}...'")
    
    conn.commit()
    conn.close()
    
    return is_new

def should_process_transaction(transaction, ignore_senders):
    """Перевіряємо чи потрібно обробляти цю транзакцію"""
    tx_id = transaction.get('id', '')
    amount = transaction.get('amount', 0) / 100
    
    # Перевіряємо що це вхідний платіж (сума > 0)
    if transaction.get('amount', 0) <= 0:
        logger.info(f"Пропускаємо транзакцію {tx_id} (не вхідний платіж, сума: {amount:.2f} грн)")
        return False
    
    # Перевіряємо що відправник не в списку ігнорованих
    counter_name = transaction.get('counterName', '')
    for ignore_sender in ignore_senders:
        if ignore_sender.strip() in counter_name:
            logger.info(f"Пропускаємо транзакцію {tx_id} (від '{ignore_sender.strip()}')")
            return False
    
    logger.info(f"Транзакція {tx_id} відповідає критеріям для обробки (сума: {amount:.2f} грн)")
    return True

def send_transaction_email(transaction, client_name, settings):
    """Відправка повідомлення про одну транзакцію"""
    tx_id = transaction.get('id', '')
    amount = transaction.get('amount', 0) / 100
    description = transaction.get('description', '')
    short_desc = description[:30] + '...' if len(description) > 30 else description
    
    logger.info(f"Підготовка до відправки повідомлення для транзакції {tx_id} ({amount:.2f} грн)")
    
    # Форматуємо дату і час з київським часовим поясом
    tx_timestamp = transaction.get('time', 0)
    tx_time = datetime.fromtimestamp(tx_timestamp, KYIV_TZ).strftime('%d.%m.%Y %H:%M')
    now = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M")
    
    subject = f"Новий платіж Monobank: {amount:.2f} грн - {short_desc}"
    
    # Створюємо красивий HTML для листа
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: 'Helvetica Neue', Arial, sans-serif;
                color: #333;
                line-height: 1.6;
                margin: 0;
                padding: 0;
                background-color: #f9f9f9;
            }}
            .container {{
                max-width: 700px;
                margin: 20px auto;
                background: #fff;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                padding: 25px;
            }}
            h1 {{
                color: #333;
                font-size: 24px;
                margin-top: 0;
                border-bottom: 2px solid #f0f0f0;
                padding-bottom: 10px;
            }}
            .header-info {{
                color: #666;
                font-size: 14px;
                margin-bottom: 20px;
            }}
            .transaction {{
                background: #f7f9fc;
                border-left: 4px solid #22a9d1;
                border-radius: 4px;
                padding: 15px;
                margin-bottom: 15px;
                transition: all 0.3s;
            }}
            .amount {{
                font-size: 24px;
                font-weight: bold;
                color: #28a745;
                margin-bottom: 5px;
            }}
            .time {{
                color: #6c757d;
                font-size: 14px;
                margin-bottom: 10px;
            }}
            .description {{
                margin: 10px 0;
                font-size: 16px;
                font-weight: 500;
            }}
            .details {{
                display: flex;
                margin-top: 15px;
                font-size: 14px;
                color: #666;
            }}
            .detail-item {{
                margin-right: 15px;
            }}
            .sender {{
                background: #f0f0f0;
                border-radius: 3px;
                padding: 8px 12px;
                margin-top: 12px;
                font-style: italic;
                color: #555;
                font-size: 15px;
            }}
            .comment {{
                margin-top: 12px;
                padding: 8px 12px;
                background: #fff8e1;
                border-radius: 3px;
                font-size: 14px;
                border-left: 2px solid #ffd54f;
            }}
            .footer {{
                margin-top: 30px;
                font-size: 12px;
                color: #999;
                text-align: center;
                border-top: 1px solid #eee;
                padding-top: 15px;
            }}
            .logo {{
                color: #22a9d1;
                font-weight: bold;
                font-size: 18px;
                text-decoration: none;
            }}
            .id-field {{
                font-family: monospace;
                background: #f5f5f5;
                padding: 3px 6px;
                border-radius: 3px;
                font-size: 13px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Новий платіж на рахунок Monobank</h1>
            <div class="header-info">
                <p>Клієнт: <strong>{client_name}</strong></p>
                <p>Повідомлення створено: {now} (Київ, UTC+3)</p>
            </div>
            
            <div class="transaction">
                <div class="amount">{amount:.2f} грн</div>
                <div class="time">Дата операції: {tx_time} (Київ, UTC+3)</div>
                <div class="description">{description}</div>
                
                <div class="details">
                    <div class="detail-item">MCC: {transaction.get('mcc', 'Невідомо')}</div>
                    <div class="detail-item">ID: <span class="id-field">{tx_id}</span></div>
                </div>
                
                {f'<div class="sender">Відправник: {transaction.get("counterName", "")}</div>' if transaction.get("counterName") else ""}
                
                {f'<div class="comment">Коментар: {transaction.get("comment", "")}</div>' if transaction.get("comment") else ""}
            </div>
            
            <div class="footer">
                <p>Це автоматичне повідомлення від системи моніторингу платежів Monobank.</p>
                <p><span class="logo">Mono</span>Monitor</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    # Створюємо повідомлення
    msg = MIMEMultipart()
    msg['From'] = settings['smtp_sender']
    msg['To'] = ', '.join(settings['smtp_recipients'])
    msg['Subject'] = subject
    
    # Додаємо HTML
    msg.attach(MIMEText(html, 'html'))
    
    try:
        # Відправляємо лист
        logger.info(f"Відправка повідомлення для транзакції {tx_id} через SMTP {settings['smtp_server']}:{settings['smtp_port']}")
        server = smtplib.SMTP(settings['smtp_server'], settings['smtp_port'])
        server.starttls()
        server.login(settings['smtp_username'], settings['smtp_password'])
        server.send_message(msg)
        server.quit()
        
        logger.info(f"Успішно відправлено повідомлення для транзакції {tx_id}")
        return True
        
    except Exception as e:
        logger.error(f"Помилка відправки листа для транзакції {tx_id}: {e}")
        return False

def mark_as_processed(transaction_id, db_file):
    """Позначити транзакцію як оброблену"""
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    
    c.execute("UPDATE transactions SET processed = 1 WHERE id = ?", (transaction_id,))
    
    conn.commit()
    conn.close()
    
    logger.info(f"Транзакція {transaction_id} позначена як оброблена")

def process_unprocessed_transactions(client_name, settings):
    """Обробляємо невідправлені транзакції з бази"""
    logger.info("Пошук невідправлених транзакцій в базі даних")
    conn = sqlite3.connect(settings['db_file'])
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("""
        SELECT t.*, a.iban
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        WHERE t.processed = 0 AND t.amount > 0
        ORDER BY t.time DESC
    """)
    
    transactions = []
    for row in c.fetchall():
        tx = dict(row)
        transactions.append(tx)
    
    conn.close()
    
    logger.info(f"Знайдено {len(transactions)} невідправлених транзакцій")
    
    count = 0
    for tx in transactions:
        if should_process_transaction(tx, settings['ignore_senders']):
            if send_transaction_email(tx, client_name, settings):
                mark_as_processed(tx['id'], settings['db_file'])
                count += 1
    
    if count > 0:
        logger.info(f"Оброблено {count} раніше невідправлених транзакцій")
    else:
        logger.info("Невідправлених транзакцій не знайдено або всі були пропущені")

def get_client_name(db_file):
    """Отримати ім'я клієнта з бази даних"""
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    
    c.execute("SELECT name FROM clients LIMIT 1")
    result = c.fetchone()
    
    conn.close()
    
    name = result[0] if result else "Клієнт Monobank"
    logger.info(f"Отримано ім'я клієнта: {name}")
    return name

def main():
    global logger
    
    # Налаштування логування
    logger = setup_logging()
    
    # Отримання налаштувань з .env файлу
    settings = get_settings()
    
    # Створюємо базу даних, якщо вона ще не існує
    create_db(settings['db_file'])
    
    try:
        logger.info(f"============= ПОЧАТОК РОБОТИ: {datetime.now(KYIV_TZ).strftime('%d.%m.%Y %H:%M:%S')} (Київський час) =============")
        logger.info(f"Період для отримання транзакцій: {settings['days_to_fetch']} днів")
        
        # Отримуємо інформацію про клієнта
        client_data = get_client_info(settings['token'], settings['api_base_url'])
        
        # Зберігаємо дані клієнта
        save_client_info(client_data, settings['db_file'])
        client_name = client_data.get('name', 'Клієнт Monobank')
        
        # Обробляємо невідправлені транзакції з попередніх запусків
        process_unprocessed_transactions(client_name, settings)
        
        # Контроль загальної кількості транзакцій
        total_transactions = 0
        processed_transactions = 0
        skipped_transactions = 0
        
        # Для кожного рахунку отримуємо виписки
        for i, account in enumerate(client_data.get('accounts', [])):
            account_id = account.get('id')
            if account_id:
                # Додаємо паузу перед кожним запитом окрім першого
                if i > 0:
                    logger.info(f"Пауза {settings['api_delay']} секунд для уникнення обмежень API...")
                    time.sleep(settings['api_delay'])
                
                logger.info(f"Отримання виписки для рахунку {account_id} (тип: {account.get('type', '')})")
                statements = get_statements(
                    settings['token'], 
                    settings['api_base_url'], 
                    account_id, 
                    days=settings['days_to_fetch']
                )
                
                total_account_transactions = len(statements)
                processed_account_transactions = 0
                skipped_account_transactions = 0
                
                logger.info(f"Почато обробку {total_account_transactions} транзакцій для рахунку {account_id}")
                
                # Обробляємо кожну транзакцію окремо відразу
                for tx_idx, tx in enumerate(statements):
                    tx_id = tx.get('id', '')
                    logger.info(f"Обробка транзакції {tx_idx+1}/{total_account_transactions}: {tx_id}")
                    
                    # Перевіряємо чи потрібно обробляти цю транзакцію
                    if should_process_transaction(tx, settings['ignore_senders']):
                        # Зберігаємо транзакцію і перевіряємо чи вона нова
                        is_new = save_transaction(account_id, tx, settings['db_file'])
                        
                        if is_new:
                            # Додаємо account_id для сумісності
                            tx['account_id'] = account_id
                            
                            # Відправляємо електронний лист
                            if send_transaction_email(tx, client_name, settings):
                                # Позначаємо як оброблену
                                mark_as_processed(tx['id'], settings['db_file'])
                                processed_account_transactions += 1
                            else:
                                logger.warning(f"Не вдалося відправити повідомлення для транзакції {tx_id}")
                        else:
                            logger.info(f"Транзакція {tx_id} вже оброблена, пропускаємо")
                            skipped_account_transactions += 1
                    else:
                        logger.info(f"Транзакція {tx_id} не відповідає критеріям, пропускаємо")
                        skipped_account_transactions += 1
                
                logger.info(f"Завершено обробку транзакцій для рахунку {account_id}:")
                logger.info(f"  - Оброблено: {processed_account_transactions}")
                logger.info(f"  - Пропущено: {skipped_account_transactions}")
                logger.info(f"  - Усього: {total_account_transactions}")
                
                total_transactions += total_account_transactions
                processed_transactions += processed_account_transactions
                skipped_transactions += skipped_account_transactions
        
        logger.info("============= ПІДСУМОК =============")
        logger.info(f"Загальна кількість транзакцій: {total_transactions}")
        logger.info(f"Оброблено нових транзакцій: {processed_transactions}")
        logger.info(f"Пропущено транзакцій: {skipped_transactions}")
        logger.info(f"============= КІНЕЦЬ РОБОТИ: {datetime.now(KYIV_TZ).strftime('%d.%m.%Y %H:%M:%S')} (Київський час) =============")
                    
    except Exception as e:
        logger.error(f"Критична помилка: {e}", exc_info=True)

if __name__ == "__main__":
    main()