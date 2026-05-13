## ⚙️ Скрипт интеграции Dr.Web GSS и Squid

Версия: 1.0.0

Настройка интеграции антивируса Dr.Web ICAPD с прокси-сервером Squid на Unix системах.

---

### 🎯 Назначение проекта

Автоматизировать процесс подключения Dr.Web ICAPD к прокси-серверу Squid.

---

### 💡 Примеры применения

Команды настройки (`setup`) и удаления (`remove`) требуют прав суперпользователя (`sudo`) для изменения конфигурационных файлов и перезапуска служб.

#### **Показать справку**

Чтобы увидеть все доступные команды и параметры, выполните:

```bash
  python3 drweb_squid_integration.py -h
```

#### **Автоматическая настройка**

Настройка интеграции Dr.Web ICAPD c прокси-сервером Squid с настройками по умолчанию.

```bash
  sudo python3 drweb_squid_integration.py setup
```

Настройка интеграции Dr.Web ICAPD c прокси-сервером Squid с настройкой разбора HTTPS трафика.

```bash
  sudo python3 drweb_squid_integration.py setup --with-ssl
```

Вы также можете указать нестандартный сокет ICAPD:

```bash
  sudo python3 drweb_squid_integration.py setup --icapd-host 127.0.0.1 --icapd-port 1345 
```

Также вы можете указать нестандартный порт Squid

```bash
  sudo python3 drweb_squid_integration.py setup --squid-port 3129 
```


#### **Настройка с отладкой и лог-файлом**

Если что-то идет не так, используйте режим отладки (`-d`) для максимально подробного вывода и сохраните весь процесс в лог-файл (`-l`).

```bash
  sudo python3 drweb_squid_integration.py setup -d -l /var/log/drweb_squid_integration.log
```

#### **Явное указание директории Squid**

Если скрипт не может автоматически найти директорию Squid, вы можете указать путь вручную:

```bash
  sudo python3 drweb_squid_integration.py setup --squid-config-dir /etc/squid
```

#### **Удаление интеграции**

Команда удалит конфигурационный блок интеграции Squid и ICAPD из файла `squid.conf`.

```bash
  sudo python3 drweb_squid_integration.py remove
```

Удаление ранее сделанных настроек, в том числе расшифровку HTTPS трафика".

```bash
  sudo python3 drweb_squid_integration.py remove --with-ssl
```

Для автоматического выполнения без запроса подтверждения добавьте флаг `-y`:

```bash
  sudo python3 drweb_squid_integration.py remove -y
```

---


### Безопасность

*   Перед каждым изменением конфигурационного файла Squid (squid.conf) создается резервная копия с меткой времени.
*   После внесения изменений и **перед** перезапуском Squid всегда выполняется команда `squid -k parse` для проверки корректности синтаксиса.
*   Команда `remove` удаляет интеграцию ICAPD с прокси-сервером squid. Флаг `--with-ssl` удалит так же настройки ssl_bump для squid, в том случае, если они ранее были добавлены скриптом. 


---

### 📁 Лицензия

MIT — свободно используйте, модифицируйте и распространяйте.
