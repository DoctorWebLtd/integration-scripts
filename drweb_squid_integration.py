import argparse
import sys
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path



__version__ = "0.0.1"

BLOCK_HEADER = "# --- BEGIN Dr.Web integration managed by script ---"
BLOCK_FOOTER = "# --- END Dr.Web integration managed by script ---"

SSL_BLOCK_HEADER = "# --- BEGIN SSL bump configuration managed by Dr.Web script ---"
SSL_BLOCK_FOOTER = "# --- END SSL bump configuration managed by Dr.Web script ---"
class AnsiColors:
    """
    Класс-хранилище для ANSI-кодов цветов.
    Используется для форматирования вывода в терминале.
    """
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class Logger:
    """
    Класс для управления выводом сообщений.
    Обеспечивает одновременный вывод в консоль (с цветом) и в лог-файл (без цвета).
    """

    def __init__(self):
        """Инициализирует логгер с настройками по умолчанию."""
        self.debug_mode = False
        self.color_enabled = sys.stdout.isatty()
        self.log_file_path = None
        self.log_file = None

    def reconfigure(self, debug_mode=False, color_enabled=True, log_file=None):
        """
        Переконфигурирует логгер на основе параметров командной строки.

        :param debug_mode: Включить ли отладочный вывод.
        :param color_enabled: Включить ли цветной вывод.
        :param log_file: Путь к файлу для логирования.
        """
        self.debug_mode = debug_mode
        self.color_enabled = color_enabled and sys.stdout.isatty()
        if self.log_file_path != log_file:
            if self.log_file:
                self.log_file.close()
            self.log_file_path = log_file
            if self.log_file_path:
                try:
                    self.log_file = open(self.log_file_path, 'a', encoding='utf-8')
                except IOError as e:
                    sys.stderr.write(f"ПРЕДУПРЕЖДЕНИЕ: Не удалось открыть лог-файл '{self.log_file_path}': {e}\n")
                    self.log_file = None

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Удаляет ANSI-коды из строки."""
        return re.sub(r'\033\[[0-9;]*m', '', text)

    def _write(self, message: str):
        """Основной метод записи в stdout и в файл."""
        print(message)
        if self.log_file:
            self.log_file.write(Logger._strip_ansi(message) + '\n')
            self.log_file.flush()

    def _colorize(self, text: str, color: str) -> str:
        """Оборачивает текст в ANSI-коды цвета."""
        return f"{color}{text}{AnsiColors.ENDC}" if self.color_enabled else text

    def info(self, message: str):
        """Выводит информационное сообщение."""
        self._write(message)

    def success(self, message: str):
        """Выводит сообщение об успехе (зеленым)."""
        self._write(self._colorize(message, AnsiColors.OKGREEN))

    def warning(self, message: str):
        """Выводит предупреждение (желтым)."""
        self._write(self._colorize(message, AnsiColors.WARNING))

    def error(self, message: str, to_stderr=True):
        """Выводит сообщение об ошибке (красным)."""
        formatted_message = self._colorize(message, AnsiColors.FAIL)
        if to_stderr:
            if self.log_file:
                self.log_file.write(Logger._strip_ansi(formatted_message) + '\n')
                self.log_file.flush()
            print(formatted_message, file=sys.stderr)
        else:
            self._write(formatted_message)

    def debug(self, message: str):
        """Выводит отладочное сообщение."""
        if self.debug_mode:
            self._write(self._colorize(f"[DEBUG] {message}", AnsiColors.OKCYAN))

    def header(self, message: str):
        """Выводит заголовок (жирным)."""
        self._write(self._colorize(message, AnsiColors.BOLD))

    def __del__(self):
        """Закрывает файл лога при уничтожении объекта."""
        if self.log_file:
            self.log_file.close()


# Глобальный экземпляр логгера, который будет переконфигурирован в main().
logger = Logger()


def check_root():
    """
    Проверяет, запущен ли скрипт от имени root.
    В случае неудачи завершает выполнение с ошибкой.
    """
    if os.geteuid() != 0:
        logger.error("Ошибка: Эта команда требует прав суперпользователя (root). Запустите ее через sudo.")
        sys.exit(1)


def check_drweb_standalone_mode():
    """
    Проверяет режим работы Dr.Web, используя существующую функцию run_shell_command.

    Выполняет команду 'drweb-ctl ap' и ищет признаки работы в режиме централизованной
    защиты. Если они найдены, выводит сообщение об ошибке и завершает скрипт.
    """

    output = run_shell_command(['drweb-ctl', 'ap'], "Проверка режима работы Dr.Web")

    # Ищем маркеры режима Enterprise Suite
    is_enterprise_mode = "off-line" in output or "on-line" in output

    if is_enterprise_mode:
        # Используем глобальный логгер для вывода ошибки, так как он есть во всех скриптах
        error_message = (
            "Dr.Web работает работает в режиме централизованной защиты.\n"
            "Скрипт предназначен только для автономного режима работы.\n"
            "Выполнение прервано."
        )
        logger.error(error_message, to_stderr=True)
        sys.exit(1)

    logger.debug("Проверка режима Dr.Web: обнаружен автономный (standalone) режим. Продолжение работы.")


def check_drweb_license():
    """Проверка наличия лицензии Dr.Web"""
    output = run_shell_command(['drweb-ctl', 'license'])
    if "no license" in output.lower():
        logger.error("Отсутствует лицензия Dr.Web. Активируйте продукт Dr.Web и попробуйте снова.")
        sys.exit(1)


def check_squid_version(args):
    """
    Проверяет версию Squid, используя существующую функцию run_shell_command.
    Также проверяет наличие флага --enable-icap-client при компиляции Squid.

    Выполняет команду "squid --version" и ищет версию Squid и флаг --enable-icap-client.
    Если они не найдены, выводит сообщение об ошибке и завершает скрипт.  
    """

    output = run_shell_command(['squid', '--version'], "Проверка совместимости установленной версии Squid с Dr.Web")

    """ Берет первую строку вывода и ищет номер версии"""
    version_line = output.split("\n")[0]
    for ch in range(len(version_line)):
        if version_line[ch].isdigit():
            version = version_line[ch:].strip()
            break
    
    """ Проверяет поддерживается ли данная версия """
    if int(version[0]) < 3:
        logger.error("Ошибка: Версии ниже 3.0 не поддерживаются.")
        sys.exit(1)

    """ Проверяет наличие флага --enable-icap-client """
    if "--enable-icap-client" not in output:
        logger.error("Ошибка: Установленная версия Squid была скомпилирона без флага --enable-icap-client.")
        sys.exit(1)

    if args.command == 'setup':
        if args.with_ssl:
            if "--with-openssl" not in output or "--enable-ssl-crtd" not in output:
                logger.error("Ошибка: Установленная версия Squid была скомпилирона без поддержки разбора HTTPS. Перекомпилируйте squid с флагами --with-openssl и --enable-ssl-crtd.")
                sys.exit(1)         
     
    return version


def find_squid_config_dir(args) -> Path:
    """
    Находит конфигурационную директорию Squid.

    Сначала проверяет, не указан ли путь в аргументах. Затем пытается
    определить его автоматически.

    :param args: Объект с аргументами командной строки.
    :raises FileNotFoundError: Если директория не найдена.
    :return: Объект Path к директории.
    """
    if args.squid_config_dir:
        config_dir = Path(args.squid_config_dir)
        if config_dir.is_dir():
            logger.debug(f"Используется директория Squid, указанная вручную: {config_dir}")
            return config_dir
        else:
            raise FileNotFoundError(f"Указанная директория Squid не найдена: {config_dir}")

    logger.debug("Автоматическое определение директории Squid...")
    # Попытка найти директрорию Squid вручную
    for path in ["/etc/squid", "/usr/local/etc/squid", "/usr/local/squid"]:
        config_dir = Path(path)
        if config_dir.is_dir():
            logger.debug(f"Найдена директория Squid: {config_dir}")
            return config_dir

    raise FileNotFoundError("Не удалось автоматически определить конфигурационную директорию Squid.")


def run_shell_command(command: list, title: str = ""):
    """
    Выполняет внешнюю команду в оболочке ОС.

    :param command: Список, содержащий команду и ее аргументы.
    :param title: Описание действия для логирования.
    :raises RuntimeError: Если команда завершается с ошибкой.
    :return: Строка с stdout выполненной команды.
    """
    if title:
        logger.debug(f"--- {title} ---")
    logger.debug(f"Выполнение shell-команды: {' '.join(command)}")
    try:
        process = subprocess.run(
            command, capture_output=True, text=True, check=True, timeout=300
        )
        if process.stdout.strip():
            logger.debug(f"STDOUT:\n{process.stdout.strip()}")
        return process.stdout.strip()
    except subprocess.CalledProcessError as e:
        error_message = (
            f"Команда '{' '.join(e.cmd)}' завершилась с ошибкой (код {e.returncode}).\n"
            f"STDERR: {e.stderr.strip()}"
        )
        raise RuntimeError(error_message)
    except FileNotFoundError:
        raise RuntimeError(f"Команда '{command[0]}' не найдена. Убедитесь, что утилита установлена и доступна в PATH.")
    except Exception as e:
        raise RuntimeError(f"Непредвиденная ошибка при выполнении команды: {e}")


def check_squid_syntax():
    """
    Запускает `squid -k parse` для проверки синтаксиса конфигурации.

    :raises RuntimeError: Если проверка синтаксиса провалилась.
    """
    try:
        run_shell_command(['squid', '-k', 'parse'], title="Проверка синтаксиса конфигурации Squid")
        logger.success("[+] Конфигурация Squid корректна.")
    except RuntimeError as e:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Проверка конфигурации Squid провалилась!", to_stderr=False)
        logger.error("Служба Squid не будет перезапущена, чтобы избежать сбоя.", to_stderr=False)
        raise e


def get_squid_conf_lines(args, version):
    squid_socket = f"{args.listen_host}:{args.listen_port}"
    
    main_cf_lines_v3_2 = [
        "icap_enable on",
        f"icap_service i_req reqmod_precache bypass=0 icap://{squid_socket}/reqmod",
        f"icap_service i_res respmod_precache bypass=0 icap://{squid_socket}/respmod",
        "adaptation_access i_req allow all",
        "adaptation_access i_res allow all",
        "icap_preview_enable on",
        "icap_preview_size 0",
        "adaptation_send_client_ip on",
        "adaptation_send_username on",
        "icap_persistent_connections on"
    ]
    main_cf_lines_v3_1 = [
        "icap_enable on",
        f"icap_service i_req reqmod_precache bypass=0 icap://{squid_socket}/reqmod",
        f"icap_service i_res respmod_precache bypass=0 icap://{squid_socket}/respmod",
        "adaptation_access i_req allow all",
        "adaptation_access i_res allow all",
        "icap_preview_enable on",
        "icap_preview_size 0",
        "icap_send_client_ip on",
        "icap_send_client_username on",
        "icap_persistent_connections on"
    ]
    main_cf_lines_v3_0 = [
        "icap_enable on",
        f"icap_service i_req reqmod_precache 0 icap://{squid_socket}/reqmod",
        f"icap_service i_res respmod_precache 0 icap://{squid_socket}/respmod",
        "icap_class icapd_class_req i_req",
        "icap_class icapd_class_resp i_res",
        "icap_access icapd_class_req allow all",
        "icap_access icapd_class_resp allow all",
        "icap_preview_enable on",
        "icap_preview_size 0",
        "icap_send_client_ip on",
        "icap_send_client_username on",
        "icap_persistent_connections on"
    ]

    version_major = version.split(".")[0]
    version_minor = version.split(".")[1]
    if version_major == 3 and version_minor == 0:
        main_cf_lines = main_cf_lines_v3_0
        logger.info("Squid версии 3.0 обнаружен.")
    elif version_major == 3 and version_minor == 1:
        main_cf_lines = main_cf_lines_v3_1
        logger.info("Squid версии 3.1 обнаружен.")
    else:
        main_cf_lines = main_cf_lines_v3_2
        logger.info("Squid версии 3.2 или выше обнаружен.")
    
    return main_cf_lines


def update_squid_config_file(filepath: Path, new_lines: list, ssl_lines: list):
    """
    Безопасно обновляет конфигурационный файл Squid.

    Функция находит и заменяет ранее созданный блок конфигурации,
    обрамленный маркерами. Если блок не найден, он добавляется в конец файла.

    :param filepath: Путь к файлу `squid.conf`.
    :param new_lines: Список строк для вставки в управляемый блок.
    """
    logger.debug(f"Обновление файла '{filepath}'...")
    create_backup(filepath)

    content = ""
    if filepath.exists():
        content = filepath.read_text(encoding='utf-8', errors='ignore')
        
    # Регулярное выражение для поиска нашего блока (включая переносы строк)
    block_pattern = re.compile(f"s*?{re.escape(BLOCK_HEADER)}.*?{re.escape(BLOCK_FOOTER)}s*?", re.DOTALL)

    # Формируем новый блок
    new_block = f"{BLOCK_HEADER}\n"
    new_block += "\n".join(new_lines)
    new_block += f"\n{BLOCK_FOOTER}\n"
    if ssl_lines:
        ssl_block = f"\n{SSL_BLOCK_HEADER}\n"
        ssl_block += "\n".join(ssl_lines)
        ssl_block += f"\n{SSL_BLOCK_FOOTER}\n"
    # Если блок уже существует, заменяем его. Иначе добавляем в конец.
    if block_pattern.search(content):
        logger.debug("Найден существующий блок конфигурации. Заменяем его.")
        final_content = block_pattern.sub(new_block, content)
    else:
        logger.debug("Блок конфигурации не найден. Добавляем новый в конец файла.")
        # Убедимся, что перед нашим блоком есть перенос строки
        if content and not content.endswith('\n'):
            content += '\n'
        final_content = content + "\n" + new_block
    
    if ssl_lines:
        block_pattern = re.compile(f"s*?{re.escape(SSL_BLOCK_HEADER)}.*?{re.escape(SSL_BLOCK_FOOTER)}s*?", re.DOTALL)
        if block_pattern.search(final_content):
            logger.debug("Найден существующий блок конфигурации ssl_bump. Заменяем его.")
            final_content = block_pattern.sub(ssl_block, final_content)
        else:
            logger.debug("Блок конфигурации не найден. Добавляем новый в конец файла.")
            # Убедимся, что перед нашим блоком есть перенос строки
            if final_content and not final_content.endswith('\n'):
                final_content += '\n'
            final_content = final_content + "\n" + ssl_block

    pattern = r"^http_port 3128.*$"
    replacement = f"http_port 3128 tcpkeepalive=60,30,3 ssl-bump generate-host-certificates=on dynamic_cert_mem_cache_size=20MB tls-cert={str(filepath.parent)}/ssl/squid.pem tls-key={str(filepath.parent)}/ssl/squid.key cipher=HIGH:MEDIUM:!LOW:!RC4:!SEED:!IDEA:!3DES:!MD5:!EXP:!PSK:!DSS options=NO_TLSv1,NO_SSLv3"
    replacement += "\n"
    final_content = re.sub(pattern, replacement, final_content, flags=re.MULTILINE)


    filepath.write_text(final_content, encoding='utf-8')
    logger.success(f"[+] Файл '{filepath.name}' успешно обновлен.")


def get_ssl_lines():
    """
    Создает строки конфига squid для работы ssl_bump.
    """
    try:
        if os.path.isfile("/usr/sbin/ssl_crtd"):
            cmd = "/usr/sbin/ssl_crtd"
        elif os.path.isfile("/usr/lib/squid/security_file_certgen"):
            cmd = "/usr/lib/squid/security_file_certgen"
        elif os.path.isfile("/usr/lib64/squid/security_file_certgen"):
            cmd = "/usr/lib64/squid/security_file_certgen"
        elif os.path.isfile("/usr/lib/squid/ssl_crtd"):
            cmd = "/usr/lib/squid/ssl_crtd"
        elif os.path.isfile("/usr/lib64/squid/ssl_crtd"):
            cmd = "/usr/lib64/squid/ssl_crtd"
        elif os.path.isfile("/usr/local/libexec/squid/security_file_certgen"):
            cmd = "/usr/local/libexec/squid/security_file_certgen"
        ssl_lines = [f"sslcrtd_program {cmd} -s /var/lib/squid/ssl_db -M 20MB",
                    "sslproxy_cert_error allow all",
                    "ssl_bump stare all"]
        return ssl_lines
    except:
        logger.warning("Не получилось определить необходимый конфиг для ssl-bump.")
        return


def handle_setup(args, squid_config_dir: Path, version: str):
    """
    Обрабатывает команду 'setup'.

    :param args: Объект с аргументами командной строки.
    :param squid_config_dir: Путь к директории конфигурации Squid.
    """
    
    logger.header("\nНастройка Dr.Web для работы с прокси-сервером Squid...")
    squid_socket = f"{args.listen_host}:{args.listen_port}"
    run_shell_command(['drweb-ctl', 'cfset', 'ICAPD.ListenAddress', squid_socket])
    run_shell_command(['drweb-ctl', 'cfset', 'ICAPD.Start', "Yes"])
    logger.success("[+] Dr.Web настроен.")

    logger.header("\nНастройка Squid (squid.conf)...")
    main_cf_path = squid_config_dir / 'squid.conf'
    if not main_cf_path.exists():
        raise FileNotFoundError(f"Основной файл конфигурации Squid не найден: {main_cf_path}")

    main_cf_lines = get_squid_conf_lines(args, version)
    ssl_lines = None
    if args.with_ssl:
        generate_certificate(squid_config_dir)
        prepare_ssl_db()
        ssl_lines = get_ssl_lines()
    update_squid_config_file(main_cf_path, main_cf_lines, ssl_lines)


def add_certificate_to_trusted(cert_path: Path):
    """
    Добавляет SSL сертификат с список доверенных сертификатов
    
    :param cert_path: Описание
    :type cert_path: Path
    """
    try:
        output = run_shell_command(["uname", "-a"]).lower()
        for os_type in ["debian", "ubuntu", "astra", "mint"]:
            if os_type in output:
                run_shell_command(["cp", str(cert_path), "/etc/ssl/certs/"])
                run_shell_command(["c_rehash"])              
                return
        for os_type in ["centos", "fedora", "red", "rhel"]:
            if os_type in output:
                run_shell_command(["cp", str(cert_path), "/etc/ssl/certs/"])
                run_shell_command(["c_rehash"])
                return     
        if "freebsd" in output:
            run_shell_command(["mkdir", "-p", "/usr/local/etc/ssl/certs/"])
            run_shell_command(["cp", str(cert_path), "/usr/local/etc/ssl/certs/"])
            run_shell_command(["certctl", "rehash"])
            return
    except Exception:
        logger.warning(f"Не получилось добавить созданный сертификат в список доверенных. \nПожалуйста сделайте это сами. Путь к сертификату {cert_path}")
        return


def generate_certificate(squid_dir_path: Path):
    """
    Создает самоподписанный SSL сертификат и добавляет его в список доверенных.

    :param filepath: путь к директории squid
    :type filepath: Path
    """
    try:
        #Create certificate
        ssl_dir_path = squid_dir_path / "ssl"
        run_shell_command(["mkdir", "-p", str(ssl_dir_path)])
        cert_path = ssl_dir_path / "squid.pem"
        run_shell_command(["openssl", "req", "-new", "-newkey", "rsa:2048", "-sha256", "-days", "3650", "-nodes", "-x509", "-extensions", "v3_ca", "-keyout", str(ssl_dir_path / "squid.key"), "-out", str(cert_path), "-subj", "/C=RU/ST=SPB/L=SPB/O=Dr.Web/OU=IT/CN=proxy.drweb.com"])
        #Add certificate to trusted
        run_shell_command(["chmod", "-R", "+r", str(ssl_dir_path)])
        add_certificate_to_trusted(cert_path)
        
    except Exception:
        logger.warning(f"Не получилось создать SSL-сертификат. Пожалуйста сделайте это самостоятельно.")
        return


def prepare_ssl_db():
    """
    Создает базу данных SSL сертификатов для работы squid 
    """
    try:
        if os.path.isfile("/usr/sbin/ssl_crtd"):
            cmd = "/usr/sbin/ssl_crtd"
        elif os.path.isfile("/usr/lib/squid/security_file_certgen"):
            cmd = "/usr/lib/squid/security_file_certgen"
        elif os.path.isfile("/usr/lib64/squid/security_file_certgen"):
            cmd = "/usr/lib64/squid/security_file_certgen"
        elif os.path.isfile("/usr/lib/squid/ssl_crtd"):
            cmd = "/usr/lib/squid/ssl_crtd"
        elif os.path.isfile("/usr/lib64/squid/ssl_crtd"):
            cmd = "/usr/lib64/squid/ssl_crtd"
        elif os.path.isfile("/usr/local/libexec/squid/security_file_certgen"):
            cmd = "/usr/local/libexec/squid/security_file_certgen"
        run_shell_command(["mkdir", "-p", "/var/lib/squid"])
        run_shell_command(["rm", "-rf", "/var/lib/squid/ssl_db"])
        run_shell_command([cmd, "-c", "-s", "/var/lib/squid/ssl_db", "-M", "20MB"])
        run_shell_command(["chown", "-R", "proxy:proxy", "/var/lib/squid"])
    except Exception:
        logger.warning(f"Не получилось подготовить базу данных SSL сертификатов. Пожалуйста подготовьте ее самостоятельно.")
        return
    

def create_backup(filepath: Path):
    """
    Создает резервную копию файла с меткой времени.

    :param filepath: Объект Path к файлу для бэкапа.
    """
    if not filepath.exists():
        logger.debug(f"Файл '{filepath}' не существует, создание бэкапа пропущено.")
        return
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_path = filepath.with_suffix(f"{filepath.suffix}.{timestamp}.backup")
        shutil.copy2(filepath, backup_path)
        logger.debug(f"[*] Создана резервная копия '{filepath.name}' -> '{backup_path.name}'")
    except Exception as e:
        logger.warning(f"ПРЕДУПРЕЖДЕНИЕ: Не удалось создать резервную копию для '{filepath}': {e}")


def remove_squid_config_block(filepath: Path, with_ssl:bool):
    """
    Безопасно удаляет блок конфигурации Dr.Web из файла Squid.

    Функция находит и удаляет блок, обрамленный маркерами.
    Если блок не найден, никаких действий не производится.

    :param filepath: Путь к файлу (squid.conf).
    """
    if not filepath.exists():
        logger.debug(f"Файл '{filepath}' не существует, пропуск удаления блока.")
        return

    logger.debug(f"Проверка файла '{filepath}' на наличие блока для удаления...")
    create_backup(filepath)
    content = filepath.read_text(encoding='utf-8', errors='ignore')

    # Регулярное выражение для поиска нашего блока (включая окружающие пробелы и переносы)
    block_pattern = re.compile(f"\\s*?{re.escape(BLOCK_HEADER)}.*?{re.escape(BLOCK_FOOTER)}\\s*?", re.DOTALL)
    final_content = ""
    if block_pattern.search(content):
        logger.debug("Найден блок конфигурации. Удаляем его.")
        # Заменяем найденный блок на пустую строку
        final_content = block_pattern.sub('', content).strip()
        # Добавляем один перенос строки в конце, если файл не пустой
        if final_content:
            final_content += '\n'
        logger.success(f"[+] Блок конфигурации Dr.Web успешно удален из '{filepath.name}'.")
    else:
        logger.info(f"[*] Блок конфигурации Dr.Web не найден в '{filepath.name}'. Действий не требуется.")


    if with_ssl:
        if final_content:
            content = final_content
        block_pattern = re.compile(f"\\s*?{re.escape(SSL_BLOCK_HEADER)}.*?{re.escape(SSL_BLOCK_FOOTER)}\\s*?", re.DOTALL)
        if block_pattern.search(content):
            logger.debug("Найден блок конфигурации ssl_bump. Удаляем его.")
            # Заменяем найденный блок на пустую строку
            final_content = block_pattern.sub('', content).strip()
            # Добавляем один перенос строки в конце, если файл не пустой
            if content:
                final_content += '\n'

            pattern = r"^http_port 3128.*$"
            replacement = f"http_port 3128"
            replacement += "\n"
            final_content = re.sub(pattern, replacement, final_content, flags=re.MULTILINE)

            logger.success(f"[+] Блок конфигурации ssl_bump успешно удален из '{filepath.name}'.")
        else:
            logger.info(f"[*] Блок конфигурации ssl_bump не найден в '{filepath.name}'. Действий не требуется.")
    
    if final_content:
        filepath.write_text(final_content, encoding='utf-8')
    return

def handle_remove(args, squid_config_dir: Path):
    """
    Обрабатывает команду 'remove', удаляя конфигурацию Dr.Web.

    :param args: Объект с аргументами командной строки.
    :param squid_config_dir: Путь к директории конфигурации Squid.
    """
    logger.header("\nУдаление конфигурации Dr.Web из Squid...")
    if not args.yes:
        confirm = input("--> Вы уверены, что хотите удалить конфигурацию Dr.Web из Squid? [y/N]: ").lower()
        if confirm != 'y':
            logger.warning("Операция отменена пользователем.")
            sys.exit(0)

    # Удаление может затронуть оба файла, поэтому проверяем оба.
    main_cf_path = squid_config_dir / 'squid.conf'

    remove_squid_config_block(main_cf_path, args.with_ssl)

    run_shell_command(['drweb-ctl', 'cfset', '-r', 'ICAPD.ListenAddress'])


def main():
    """
    Главная функция: парсинг аргументов и вызов обработчиков.
    """
    parser = argparse.ArgumentParser(
        description=f"Скрипт для интеграции Dr.Web и Squid. Версия {__version__}.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="Примеры использования:\n"
               "  # Настройка интеграции Dr.Web и Squid со значениями по умолчанию:\n"
               "  sudo ./%(prog)s setup\n\n"
               "  # Настройка интеграции Dr.Web и Squid с разбором HTTPS трафика"
               "  sudo ./%(prog)s setup --with-ssl"
               "  # Настройка с указанием хоста и порта Dr.Web:\n"
               "  sudo ./%(prog)s setup --icapd-port 1345 --icapd-host 127.0.0.1\n\n"
               "  # Удаление ранее сделанных настроек с автоматическим подтверждением:\n"
               "  sudo ./%(prog)s remove -y\n\n"
               "  # Удаление ранее сделанных настроек, в том числе расшифровку HTTPS трафика"
               "  sudo ./%(prog)s remove --with-ssl"
               "  # Запустить настройку с записью всего вывода в лог-файл:\n"
               "  sudo ./%(prog)s setup -l /var/log/drweb_squid_setup.log"
    )
    parser.add_argument('-v', '--version', action='version', version=f'%(prog)s {__version__}')
    subparsers = parser.add_subparsers(dest='command', required=True, help='Доступные команды')

    # --- Родительские парсеры для общих опций ---
    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument('--squid-config-dir', type=str,
                             help='Явно указать путь к директории конфигурации Squid (например, /etc/squid).')
    base_parser.add_argument('-l', '--log-file', default=None, help='Сохранять весь вывод в файл журнала.')
    base_parser.add_argument('-d', '--debug', action='store_true', help='Включить подробный отладочный вывод.')
    base_parser.add_argument('--no-color', action='store_true', help='Отключить цветной вывод.')
    base_parser.add_argument('--with-ssl', dest="with_ssl", default=False, action='store_true',
                               help='Провести настройку squid для разбора HTTPS трафика.')

    interactive_parser = argparse.ArgumentParser(add_help=False)
    interactive_parser.add_argument('-y', '--yes', action='store_true',
                                    help='Пропустить интерактивные запросы подтверждения.')

    # --- Суб-парсер для команды 'setup' ---
    parser_icapd = subparsers.add_parser('setup', parents=[base_parser],
                                          help='Настройка интеграции через ICAPD.')
    parser_icapd.add_argument('--listen-host', dest="listen_host", default='127.0.0.1',
                               help='Хост для ICAPD-сокета (по умолч.: 127.0.0.1).')
    parser_icapd.add_argument('--listen-port', dest="listen_port", default=1344, type=int,
                               help='Порт для ICAPD-сокета (по умолч.: 1344).')

    # --- Суб-парсер для команды 'remove' ---
    subparsers.add_parser('remove', parents=[base_parser, interactive_parser],
                          help='Удаление ранее сделанных настроек.')

    args = parser.parse_args()
    logger.reconfigure(debug_mode=args.debug, color_enabled=not args.no_color, log_file=args.log_file)
    try:
        check_root()
        check_drweb_license()
        check_drweb_standalone_mode()
        squid_config_dir = find_squid_config_dir(args)
        version = check_squid_version(args)
        # Вызов соответствующего обработчика
        if args.command == 'setup':
            handle_setup(args, squid_config_dir, version)
        elif args.command == 'remove':
            handle_remove(args, squid_config_dir)

        logger.header("\nПроверка конфигурации и перезапуск сервисов...")
        check_squid_syntax()
        if "freebsd" in run_shell_command(["uname", "-a"]).lower():
            run_shell_command(["service", "squid", "restart"], title="Перезапуск Squid")
        else:
            run_shell_command(['systemctl', 'restart', 'squid'], title="Перезапуск Squid")

        # Перезапускаем Dr.Web только при настройке, а не при удалении
        if args.command.startswith('setup'):
            if "freebsd" in run_shell_command(["uname", "-a"]).lower():
                run_shell_command(["service", "drweb-configd", "restart"], title="Перезапуск Dr.Web ConfigD")
            else:
                run_shell_command(['systemctl', 'restart', 'drweb-configd'], title="Перезапуск Dr.Web ConfigD")

        logger.success("\n[+] Сервисы успешно перезапущены.")
        logger.info("\nОперация успешно завершена.")
        if args.with_ssl and args.command == "setup":
            logger.info(f"\nВы можете найти SSL сертификат по следующем пути: {str(squid_config_dir)}/ssl/squid.pem")

    except (RuntimeError, IOError, ValueError, FileNotFoundError, PermissionError) as e:
        logger.error(f"\nКРИТИЧЕСКАЯ ОШИБКА: {e}", to_stderr=True)
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nНЕПРЕДВИДЕННАЯ ОШИБКА: {e}", to_stderr=True)
        logger.debug("Полная трассировка ошибки:")
        import traceback
        logger.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
