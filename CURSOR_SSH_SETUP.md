# Подключение Cursor к дроплету через SSH

## Шаг 1: Узнай IP адрес дроплета

1. Войди в панель DigitalOcean
2. Перейди в раздел "Droplets"
3. Найди свой дроплет и скопируй его **IP адрес** (например: `167.172.103.156`)

## Шаг 2: Настрой SSH config (рекомендуется)

Это позволит подключаться к серверу по короткому имени вместо IP адреса.

### Вариант A: Через Cursor (проще)

1. Открой Cursor
2. Нажми `Ctrl+Shift+P` (или `Cmd+Shift+P` на Mac)
3. Введи: `Remote-SSH: Open SSH Configuration File`
4. Выбери файл: `C:\Users\Admin\.ssh\config` (Windows) или `~/.ssh/config` (Mac/Linux)
5. Добавь в конец файла:

```
Host gs-droplet
    HostName YOUR_DROPLET_IP
    User root
    IdentityFile ~/.ssh/id_rsa
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

**Замени `YOUR_DROPLET_IP` на реальный IP адрес твоего дроплета!**

### Вариант B: Вручную через файловый менеджер

1. Открой файл: `C:\Users\Admin\.ssh\config` в любом текстовом редакторе
2. Добавь туда конфигурацию выше
3. Сохрани файл

## Шаг 3: Подключение через Cursor

### Способ 1: Через Command Palette (рекомендуется)

1. В Cursor нажми `Ctrl+Shift+P`
2. Введи: `Remote-SSH: Connect to Host...`
3. Выбери `gs-droplet` (или введи `root@YOUR_DROPLET_IP` напрямую)
4. Cursor откроет новое окно и подключится к серверу
5. При первом подключении выбери платформу сервера (обычно Linux)
6. Дождись установки расширений на сервер (происходит автоматически)

### Способ 2: Через нижний левый угол

1. Нажми на зеленую кнопку в левом нижнем углу Cursor (показывает "><")
2. Выбери "Connect to Host..."
3. Выбери `gs-droplet` или введи `root@YOUR_DROPLET_IP`

## Шаг 4: Открыть папку проекта на сервере

После подключения:

1. Нажми `Ctrl+K Ctrl+O` (или File → Open Folder)
2. Введи путь к проекту: `/opt/gs-video-converter` (или другую директорию, где будет проект)
3. Если папки еще нет, создай её через терминал в Cursor

## Шаг 5: Проверка подключения

Открой терминал в Cursor (`Ctrl+`` или View → Terminal) и выполни:

```bash
whoami
pwd
ls -la
```

Должен показать, что ты подключен как `root` (или другой пользователь) и находишься на сервере.

## Устранение проблем

### Ошибка "Permission denied (publickey)"

**Решение:**
1. Убедись, что SSH ключ добавлен в DigitalOcean (Settings → Security → SSH Keys)
2. Проверь, что в SSH config указан правильный путь к ключу:
   ```
   IdentityFile ~/.ssh/id_rsa
   ```
3. Если используешь другой ключ, укажи его путь

### Ошибка "Host key verification failed"

**Решение:**
1. Открой терминал (PowerShell)
2. Выполни: `ssh root@YOUR_DROPLET_IP`
3. Введи `yes` когда спросит про fingerprint
4. Попробуй подключиться через Cursor снова

### Cursor не видит хост в списке

**Решение:**
1. Убедись, что SSH config файл сохранен
2. Перезапусти Cursor
3. Или подключись напрямую: `root@YOUR_DROPLET_IP`

### Медленное подключение

**Решение:**
Добавь в SSH config (уже добавлено в примере выше):
```
ServerAliveInterval 60
ServerAliveCountMax 3
```

Это будет поддерживать соединение активным.

## Полезные команды Cursor для Remote-SSH

- `Ctrl+Shift+P` → `Remote-SSH: Connect to Host` - подключиться к хосту
- `Ctrl+Shift+P` → `Remote-SSH: Disconnect` - отключиться
- `Ctrl+Shift+P` → `Remote-SSH: Kill VS Code Server on Host` - перезапустить сервер на удаленной машине
- `Ctrl+Shift+P` → `Remote-SSH: Open Configuration File` - открыть SSH config

## Следующие шаги

После успешного подключения:

1. Клонируй репозиторий на сервер:
   ```bash
   cd /opt
   git clone https://github.com/cellobasil/GS-video-converter.git gs-video-converter
   ```

2. Следуй инструкциям из `DEPLOYMENT_GUIDE.md` для настройки окружения

3. Теперь можешь редактировать код прямо на сервере через Cursor!
