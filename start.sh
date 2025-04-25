#!/bin/bash

# Шлях до директорії проекту
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Налаштування
VENV_DIR="$PROJECT_DIR/venv"
PYTHON_SCRIPT="$PROJECT_DIR/main.py"
LOG_FILE="$PROJECT_DIR/logs/cron_run.log"

# Перевірка наявності віртуального середовища
if [ ! -d "$VENV_DIR" ]; then
    echo "Віртуальне середовище не знайдено. Створюємо нове..."
    python3 -m venv "$VENV_DIR"
    
    # Активація віртуального середовища та встановлення залежностей
    source "$VENV_DIR/bin/activate"
    pip install -r "$PROJECT_DIR/requirements.txt"
else
    echo "Віртуальне середовище знайдено."
    source "$VENV_DIR/bin/activate"
fi

# Створення директорії для логів, якщо її не існує
mkdir -p "$PROJECT_DIR/logs"

# Запуск скрипта один раз зараз
echo "Запуск моніторингу Monobank..."
python "$PYTHON_SCRIPT"

# Команда, яка буде додана в crontab
CRON_COMMAND="*/1 * * * * cd $PROJECT_DIR && $VENV_DIR/bin/python $PYTHON_SCRIPT >> $LOG_FILE 2>&1"

# Перевірка чи існує вже ця команда в crontab
EXISTING_CRON=$(crontab -l 2>/dev/null | grep -F "$PYTHON_SCRIPT")

if [ -z "$EXISTING_CRON" ]; then
    # Додавання завдання в crontab
    echo "Додаємо завдання в crontab для запуску кожні 15 хвилин..."
    (crontab -l 2>/dev/null; echo "$CRON_COMMAND") | crontab -
    echo "Завдання успішно додано в crontab."
    echo "Скрипт буде запускатися кожні 15 хвилин."
else
    echo "Завдання вже існує в crontab. Пропускаємо додавання."
fi

# Виведення поточних завдань crontab
echo "Поточні завдання crontab:"
crontab -l

echo "Процес налаштування завершено!"
echo "Логи cron-завдання будуть записуватися в: $LOG_FILE"