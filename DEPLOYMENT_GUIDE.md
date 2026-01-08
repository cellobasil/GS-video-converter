# Инструкция по деплою GS Video Converter Bot

## Шаг 1: Подготовка сервера

### Установка зависимостей

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y  # для Ubuntu/Debian
# или
sudo yum update -y  # для CentOS/RHEL

# Установка Python и pip
sudo apt install python3 python3-pip python3-venv git -y  # Ubuntu/Debian
# или
sudo yum install python3 python3-pip git -y  # CentOS/RHEL

# Установка FFmpeg
sudo apt install ffmpeg -y  # Ubuntu/Debian
# или
sudo yum install epel-release -y && sudo yum install ffmpeg -y  # CentOS/RHEL

# Проверка версий
python3 --version  # должно быть 3.8+
ffmpeg -version
```

## Шаг 2: Клонирование проекта

```bash
# Переход в рабочую директорию
cd /opt  # или другую директорию, которую выделил разработчик
sudo mkdir -p gs-video-converter
sudo chown $USER:$USER gs-video-converter
cd gs-video-converter

# Клонирование репозитория
git clone https://github.com/cellobasil/GS-video-converter.git .

# Или если используешь SSH:
# git clone git@github.com:cellobasil/GS-video-converter.git .
```

## Шаг 3: Настройка окружения

```bash
# Создание виртуального окружения
python3 -m venv venv

# Активация виртуального окружения
source venv/bin/activate

# Установка зависимостей
pip install --upgrade pip
pip install -r requirements.txt
```

## Шаг 4: Создание конфигурации

```bash
# Создание .env файла
nano .env
```

Содержимое `.env` файла:
```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
TARGET_CHANNEL_ID=your_channel_id
ALLOWED_USER_IDS=123456789,987654321
WORK_DIR=downloads
```

**Где взять значения:**
- `API_ID` и `API_HASH`: https://my.telegram.org/apps
- `BOT_TOKEN`: от @BotFather в Telegram
- `TARGET_CHANNEL_ID`: ID канала (можно получить через бота @userinfobot)
- `ALLOWED_USER_IDS`: список ID пользователей через запятую

## Шаг 5: Создание systemd service

```bash
# Создание service файла
sudo nano /etc/systemd/system/gs-video-converter.service
```

Содержимое service файла:
```ini
[Unit]
Description=GS Video Converter Telegram Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/opt/gs-video-converter
Environment="PATH=/opt/gs-video-converter/venv/bin"
ExecStart=/opt/gs-video-converter/venv/bin/python /opt/gs-video-converter/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Важно:** Замени `your_username` на имя пользователя, под которым будет запускаться бот, и пути на актуальные.

```bash
# Перезагрузка systemd
sudo systemctl daemon-reload

# Включение автозапуска
sudo systemctl enable gs-video-converter.service

# Запуск сервиса
sudo systemctl start gs-video-converter.service

# Проверка статуса
sudo systemctl status gs-video-converter.service

# Просмотр логов
sudo journalctl -u gs-video-converter.service -f
```

## Шаг 6: Настройка логов (опционально)

```bash
# Создание директории для логов
sudo mkdir -p /var/log/gs-bot
sudo chown your_username:your_username /var/log/gs-bot

# Можно настроить ротацию логов
sudo nano /etc/logrotate.d/gs-bot
```

Содержимое logrotate:
```
/var/log/gs-bot/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

## Шаг 7: Проверка работы

```bash
# Проверка, что бот запущен
sudo systemctl status gs-video-converter.service

# Проверка логов на ошибки
sudo journalctl -u gs-video-converter.service --since "10 minutes ago"

# Проверка процесса
ps aux | grep main.py
```

## Управление сервисом

```bash
# Остановка
sudo systemctl stop gs-video-converter.service

# Запуск
sudo systemctl start gs-video-converter.service

# Перезапуск
sudo systemctl restart gs-video-converter.service

# Просмотр логов в реальном времени
sudo journalctl -u gs-video-converter.service -f

# Просмотр последних 100 строк логов
sudo journalctl -u gs-video-converter.service -n 100
```

## Обновление кода

```bash
cd /opt/gs-video-converter

# Остановка сервиса
sudo systemctl stop gs-video-converter.service

# Получение обновлений
git pull origin main

# Обновление зависимостей (если изменились)
source venv/bin/activate
pip install -r requirements.txt

# Запуск сервиса
sudo systemctl start gs-video-converter.service
```

## Подключение Cursor Agent

После получения SSH доступа:

1. В Cursor: `Ctrl+Shift+P` → "Remote-SSH: Connect to Host"
2. Введи данные сервера: `username@server_ip`
3. После подключения открой папку проекта: `/opt/gs-video-converter`
4. Cursor автоматически предложит установить расширения для удаленной разработки

Или используй SSH конфиг (`~/.ssh/config`):
```
Host gs-server
    HostName your_server_ip
    User your_username
    Port 22
    IdentityFile ~/.ssh/your_key
```

## Устранение проблем

### Бот не запускается
```bash
# Проверь логи
sudo journalctl -u gs-video-converter.service -n 50

# Проверь права на файлы
ls -la /opt/gs-video-converter

# Проверь .env файл
cat /opt/gs-video-converter/.env
```

### FFmpeg не найден
```bash
# Проверь установку
which ffmpeg
ffmpeg -version

# Если не установлен
sudo apt install ffmpeg -y
```

### Проблемы с правами
```bash
# Убедись, что пользователь имеет права на директорию
sudo chown -R your_username:your_username /opt/gs-video-converter
```

### Проблемы с сетью/Telegram API
```bash
# Проверь доступность Telegram API
curl -I https://api.telegram.org

# Проверь настройки файрвола (если есть)
sudo ufw status
```

## Мониторинг ресурсов

```bash
# Использование CPU и памяти
htop

# Использование диска
df -h

# Размер директории downloads
du -sh /opt/gs-video-converter/downloads
```
