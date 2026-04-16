import argparse
import sys
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List


__version__ = "1.0.0"

# Блоки, которые скрипт ищет в конфигурационном файле squid
BLOCK_HEADER = "# --- BEGIN Dr.Web integration managed by script ---"
BLOCK_FOOTER = "# --- END Dr.Web integration managed by script ---"
SSL_BLOCK_HEADER = "# --- BEGIN SSL bump configuration managed by Dr.Web script ---"
SSL_BLOCK_FOOTER = "# --- END SSL bump configuration managed by Dr.Web script ---"
SSL_PORT_HEADER = "# --- BEGIN SSL port configuration managed by Dr.Web script ---"
SSL_PORT_FOOTER = "# --- END SSL port configuration managed by Dr.Web script ---"

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
        logger.info("Обнаружен режим централизованной защиты. " \
        "Данный скрипт применит все необходимые настройки для squid, но настройки Dr.Web остануться прежними")
        return False
    logger.debug("Проверка режима Dr.Web: обнаружен автономный (standalone) режим. Продолжение работы.")
    return True

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

    output = run_shell_command(['squid', '-v'], "Проверка совместимости установленной версии Squid с Dr.Web")

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
    try:
        
        version = version.strip().split(".")
        minor_version = int(version[1])
        logger.debug(f"minor_version: {minor_version}")
    except (ValueError, TypeError):
        logger.error("Ошибка: Не получилось определить минорную версию squid.")
        raise
    return minor_version


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


def check_squid_syntax():
    """
    Запускает `squid -k parse` для проверки синтаксиса конфигурации.

    :raises RuntimeError: Если проверка синтаксиса провалилась.
    """
    try:
        output = run_shell_command(['squid', '-k', 'parse'], title="Проверка синтаксиса конфигурации Squid")
        if "Page faults with physical i/o" not in output:
            logger.success("[+] Конфигурация Squid корректна.")
        return output
    except RuntimeError as e:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Проверка конфигурации Squid провалилась!", to_stderr=False)
        logger.error("Служба Squid не будет перезапущена, чтобы избежать сбоя.", to_stderr=False)
        raise e


def get_squid_conf_lines(args, version:int):
    """
    Подбирает соответствующую версии squid конфигурацию. 
    Также подставляет пользовательские настройки сокета ICAPD.
    
    :param args: Объект с аргументами командной строки.
    :param version: Минорная версия squid
    """
    icapd_socket = f"{args.icapd_host}:{args.icapd_port}"

    conf_lines = ["icap_enable on",
            f"icap_service i_req reqmod_precache bypass=0 icap://{icapd_socket}/reqmod",
            f"icap_service i_res respmod_precache bypass=0 icap://{icapd_socket}/respmod"]
    
    conf_lines_mid = ["adaptation_access i_req allow all",
                    "adaptation_access i_res allow all",
                    "icap_preview_enable on",
                    "icap_preview_size 0",
                    ]

    conf_lines_end = ["icap_send_client_ip on",
                    "icap_send_client_username on",
                    "icap_persistent_connections on"]
    
    logger.debug(version)
    conf_lines  += conf_lines_mid if version >= 1 else ["icap_class icapd_class_req i_req",
                                                            "icap_class icapd_class_resp i_res",
                                                            "icap_access icapd_class_req allow all",
                                                            "icap_access icapd_class_resp allow all",
                                                            "icap_preview_enable on",
                                                            "icap_preview_size 0",]
    
    conf_lines  += conf_lines_end if version <= 1 else ["adaptation_send_client_ip on",
                                                            "adaptation_send_username on",
                                                            "icap_persistent_connections on"]


    if version == 0:
        logger.info("Squid версии 3.0 обнаружен.")
    elif version == 1:
        logger.info("Squid версии 3.1 обнаружен.")
    else:
        logger.info("Squid версии 3.2 или выше обнаружен.")
    
    return conf_lines


def _replace_or_add_block(
    content: str,
    header: str,
    footer: str,
    new_lines: List[str],
    block_name: str,
) -> str:
    """
    Заменяет существующий блок между header и footer на новый блок,
    составленный из new_lines. Если блок не найден, добавляет его в конец.

    :param content: Исходное содержимое файла
    :param header: Маркер начала блока
    :param footer: Маркер конца блока
    :param new_lines: Строки для вставки внутрь блока
    :param block_name: Имя блока для логирования
    :return: Новое содержимое с обновлённым блоком
    """
    pattern = re.compile(
        rf"\s*?{re.escape(header)}.*?{re.escape(footer)}\s*?",
        re.DOTALL,
    )
    new_block = f"{header}\n" + "\n".join(new_lines) + f"\n{footer}\n"

    if pattern.search(content):
        logger.debug(f"Найден существующий блок конфигурации '{block_name}'. Заменяем его.")
        return pattern.sub(new_block, content)
    else:
        logger.debug(f"Блок конфигурации '{block_name}' не найден. Добавляем новый в конец файла.")
        if content and not content.endswith("\n"):
            content += "\n"
        return content + "\n" + new_block


def comment_http_port_lines(content: str, squid_port: int) -> str:
    """
    Комментирует все строки http_port, содержащие указанный порт.
    """
    lines = content.splitlines()
    port_pattern = re.compile(rf"^http_port.*{squid_port}")
    commented_lines = []
    for line in lines:
        if port_pattern.search(line) and not line.strip().startswith("#"):
            line = "#drweb " + line
        commented_lines.append(line)
    return "\n".join(commented_lines)


def build_http_port_line(squid_port: int, cert_dir: Path, use_tls_cert: bool = True) -> str:
    """
    Формирует строку http_port с нужными параметрами.
    """
    cert_path = cert_dir / "ssl" / "squid.pem"
    key_path = cert_dir / "ssl" / "squid.key"
    cert_param = "tls-cert" if use_tls_cert else "cert"
    return (
        f"http_port {squid_port} tcpkeepalive=60,30,3 ssl-bump "
        f"generate-host-certificates=on dynamic_cert_mem_cache_size=20MB "
        f"{cert_param}={cert_path} tls-key={key_path} "
        f"cipher=HIGH:MEDIUM:!LOW:!RC4:!SEED:!IDEA:!3DES:!MD5:!EXP:!PSK:!DSS "
        f"options=NO_TLSv1,NO_SSLv3"
    )


def update_http_port_block(content: str, squid_port: int, cert_dir: Path) -> str:
    """
    Обрабатывает блок конфигурации http_port:
    - комментирует старые строки http_port с нужным портом,
    - заменяет или добавляет управляемый блок с новыми настройками порта.
    """
    # Сначала закомментируем существующие строки http_port
    content = comment_http_port_lines(content, squid_port)

    # Подготавливаем новый блок
    port_line = build_http_port_line(squid_port, cert_dir, use_tls_cert=True)
    port_block_lines = [f"\n{SSL_PORT_HEADER}\n", f"{port_line}\n", SSL_PORT_FOOTER]

    # Пытаемся заменить существующий блок с маркерами
    pattern = re.compile(
        rf"\s*?{re.escape(SSL_PORT_HEADER)}.*?{re.escape(SSL_PORT_FOOTER)}\s*?",
        re.DOTALL,
    )
    if pattern.search(content):
        logger.debug("Найден существующий блок конфигурации http_port. Заменяем его.")
        return pattern.sub("".join(port_block_lines), content)
    else:
        logger.debug("Блок конфигурации http_port не найден. Добавляем новый.")
        # Ищем любую строку http_port (закомментированную или нет) и вставляем блок после неё
        lines = content.splitlines()
        http_port_pattern = re.compile(r"^#?(drweb\s+)?http_port.*")
        for i, line in enumerate(lines):
            if http_port_pattern.search(line):
                # Вставляем новый блок после найденной строки
                lines[i+1:i+1] = port_block_lines
                return "\n".join(lines)
        # Если строк http_port нет вообще — добавляем в конец
        if content and not content.endswith("\n"):
            content += "\n"
        return content + "\n" + "".join(port_block_lines)


def update_squid_config_file(
    filepath: Path,
    new_lines: List[str],
    ssl_lines: List[str],
    args,
) -> None:
    """
    Безопасно обновляет конфигурационный файл Squid.

    Функция находит и заменяет ранее созданный блок конфигурации,
    обрамленный маркерами. Если блок не найден, он добавляется в конец файла.
    При наличии ssl_lines также настраивает ssl_bump и параметры http_port.

    :param filepath: Путь к файлу `squid.conf`.
    :param new_lines: Список строк для вставки в управляемый блок.
    :param ssl_lines: Список строк для блока ssl_bump (может быть пустым).
    :param args: Объект с атрибутами squid_port и другими параметрами.
    """
    try:
        logger.debug(f"Обновление файла '{filepath}'...")
        create_backup(filepath)

        # Чтение текущего содержимого
        content = ""
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8", errors="ignore")

        # 1. Обновление основного блока конфигурации
        content = _replace_or_add_block(
            content,
            BLOCK_HEADER,
            BLOCK_FOOTER,
            new_lines,
            "основной",
        )

        # 2. Если есть ssl-настройки — обрабатываем ssl_bump и http_port
        if ssl_lines:
            # Обновляем блок ssl_bump
            content = _replace_or_add_block(
                content,
                SSL_BLOCK_HEADER,
                SSL_BLOCK_FOOTER,
                ssl_lines,
                "ssl_bump",
            )

            # Обновляем блок http_port
            cert_dir = filepath.parent
            content = update_http_port_block(content, args.squid_port, cert_dir)

        # Первая запись файла (основная конфигурация)
        filepath.write_text(content, encoding="utf-8")
        logger.debug("Записана основная конфигурация.")

        # 3. Проверка конфигурации через squid -k parse (только если есть ssl_lines)
        if ssl_lines:
            logger.debug("Проверка конфигурации...")
            try:
                result = subprocess.run(
                    ["squid", "-k", "parse"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=300,
                )
                if result.stderr.strip():
                    logger.debug("Настройки порта выдали ошибку. Пробуем другую конфигурацию...")
                    # Заменяем tls-cert на cert в строке http_port внутри блока
                    cert_dir = filepath.parent
                    fallback_line = build_http_port_line(args.squid_port, cert_dir, use_tls_cert=False)
                    # Находим и заменяем строку внутри блока
                    pattern = r"^http_port.*tls-cert.*\n$"
                    content = re.sub(pattern, fallback_line + "\n", content, flags=re.MULTILINE)
                    # Перезаписываем файл с исправленной строкой
                    filepath.write_text(content, encoding="utf-8")
                    logger.debug("Конфигурация обновлена с параметром 'cert'.")
            except subprocess.TimeoutExpired:
                logger.error("Проверка squid -k parse превысила таймаут.")
            except FileNotFoundError:
                logger.error("Команда 'squid' не найдена. Проверка конфигурации пропущена.")

        logger.success(f"[+] Файл '{filepath.name}' успешно обновлен.")

    except Exception:
        logger.error("Произошла ошибка при обновлении конфигурации squid.")
        import traceback
        logger.error(traceback.format_exc())


def get_ssl_lines():
    """
    Создает строки конфига squid для работы ssl_bump.
    """
    cmds =  ["/usr/sbin/ssl_crtd",
             "/usr/lib/squid/security_file_certgen",
             "/usr/lib64/squid/security_file_certgen",
             "/usr/lib/squid/ssl_crtd",
             "/usr/lib64/squid/ssl_crtd",
             "/lib/squid/ssl_crtd",
             "/lib64/squid/ssl_crtd",
             "/usr/local/libexec/squid/security_file_certgen",
             ]
    cmd = [cmd for cmd in cmds if os.path.isfile(cmd)]
    if cmd:
        ssl_lines = [f"sslcrtd_program {cmd[0]} -s /usr/local/squid/var/lib/ssl_db -M 20MB",
                    "sslproxy_cert_error allow all",
                    "ssl_bump stare all"]
        return ssl_lines
    else:
        logger.warning("Не получилось определить необходимый конфиг для ssl-bump.")
        return


def handle_setup(args, squid_config_dir: Path, version: int, mode: bool):
    """
    Обрабатывает команду 'setup'.

    :param args: Объект с аргументами командной строки.
    :param squid_config_dir: Путь к директории конфигурации Squid.
    """
    if mode:
        logger.header("\nНастройка Dr.Web для работы с прокси-сервером Squid...")
        icapd_socket = f"{args.icapd_host}:{args.icapd_port}"
        run_shell_command(['drweb-ctl', 'cfset', 'ICAPD.ListenAddress', icapd_socket])
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
    update_squid_config_file(main_cf_path, main_cf_lines, ssl_lines, args)


def add_certificate_to_trusted(cert_path):
    """
    Добавляет SSL сертификат в список доверенных сертификатов системы

    :param cert_path: Путь к ssl сертификату
    """
    try:
        output = run_shell_command(["uname", "-a"]).lower()
        if "freebsd" in output:
            run_shell_command(["mkdir", "-p", "/usr/local/etc/ssl/certs/"])
            run_shell_command(["cp", str(cert_path), "/usr/local/etc/ssl/certs/"])
            run_shell_command(["certctl", "rehash"])
            return
        else:
            cmds = ["update-ca-certificates", "update-ca-trust", "c_rehash"]
            for cmd in cmds:
                try:
                    run_shell_command(["which", cmd])
                    if cmd == "c_rehash":    
                        run_shell_command(["cp", str(cert_path), "/etc/ssl/certs/"])
                        run_shell_command([cmd])
                        return
                    if cmd == "update-ca-certificates":
                        cert_crt = str(cert_path).replace(".pem", ".crt")
                        run_shell_command(["cp", str(cert_path), cert_crt])
                        run_shell_command(["cp", cert_crt, "/usr/local/share/ca-certificates/"])
                        run_shell_command([cmd])
                        return
                    if cmd == "update-ca-trust":
                        run_shell_command(["cp", str(cert_path), "/etc/pki/ca-trust/source/anchors/"])
                        run_shell_command([cmd])
                        return
                except Exception:
                    continue
                raise RuntimeError
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
    Создает базу данных SSL сертификатов для работы squid в режиму ssl_bump 
    """
    try:
        cmds =  ["/usr/sbin/ssl_crtd",
                "/usr/lib/squid/security_file_certgen",
                "/usr/lib64/squid/security_file_certgen",
                "/usr/lib/squid/ssl_crtd",
                "/usr/lib64/squid/ssl_crtd",
                "/lib/squid/ssl_crtd",
                "/lib64/squid/ssl_crtd",
                "/usr/local/libexec/squid/security_file_certgen",
                ]
        cmd = [cmd for cmd in cmds if os.path.isfile(cmd)]
        if cmd:
            #Определить пользователя и группу squid(может быть proxy или squid)
            try:
                output = run_shell_command(["id", "proxy"])
            except Exception:
                output = ""
            if "uid" in output:
                user = "proxy"
            else:
                user = "squid"
            run_shell_command(["mkdir", "-p", "/usr/local/squid/var/lib/"])
            run_shell_command(["rm", "-rf", "/usr/local/squid/var/lib/ssl_db"])
            run_shell_command(["chown", "-R", f"{user}:{user}", "/usr/local/squid/var/lib/"])
            run_shell_command([cmd[0], "-c", "-s", "/usr/local/squid/var/lib/ssl_db", "-M", "20MB"])
            run_shell_command(["chown", "-R", f"{user}:{user}", "/usr/local/squid"])
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
            logger.success(f"[+] Блок конфигурации ssl_bump успешно удален из '{filepath.name}'.")
        else:
            logger.info(f"[*] Блок конфигурации ssl_bump не найден в '{filepath.name}'. Действий не требуется.")
    
        if final_content:
            content = final_content

        pattern = re.compile("#drweb http_port")
        if pattern.search(content):
            content = pattern.sub("http_port",content)
        
        block_pattern = re.compile(f"s*?{re.escape(SSL_PORT_HEADER)}.*?{re.escape(SSL_PORT_FOOTER)}s*?", re.DOTALL)

        if block_pattern.search(content):
            logger.debug("Найден блок конфигурации http_port. Удаляем его.")
            final_content = block_pattern.sub("", content)
            logger.success(f"[+] Блок конфигурации http_port успешно удален.")
        else:
            logger.info(f"[*] Блок конфигурации http_port не найден в '{filepath.name}'. Действий не требуется.")
    
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
        epilog= "Параметры:\n"
                "  -squid-config-dir Явно указать путь к директории конфигурации Squid\n"
                "  --icapd-host     Хост для ICAPD-сокета (по умолч.: 127.0.0.1)\n"
                "  --icapd-port     Порт для ICAPD-сокета (по умолч.: 1344)\n"
                "  --with-ssl        Провести настройку squid для разбора HTTPS трафика\n"
                "  -l, --log-file    Сохранять весь вывод в файл журнала\n"
                "  -d, --debug       Включить подробный отладочный вывод\n"
                "  --no-color        Отключить цветной вывод\n"
                "  -y, --yes         Пропустить интерактивные запросы подтверждения\n"
                "Примеры использования:\n"
                "  # Настройка интеграции Dr.Web и Squid со значениями по умолчанию:\n"
                "  sudo ./%(prog)s setup\n\n"
                "  # Настройка интеграции Dr.Web и Squid с разбором HTTPS трафика\n"
                "  sudo ./%(prog)s setup --with-ssl\n\n"
                "  # Настройка с указанием хоста и порта Dr.Web ICAPD:\n"
                "  sudo ./%(prog)s setup --icapd-port 127.0.0.1 --icapd-host 1345 \n\n"
                "  # Настройка с указанием кастомного порта squid:\n"
                "  sudo ./%(prog)s setup --squid-port 3129\n"
                "  # Удаление ранее сделанных настроек с автоматическим подтверждением:\n"
                "  sudo ./%(prog)s remove -y\n\n"
                "  # Удаление ранее сделанных настроек, в том числе расшифровку HTTPS трафика\n"
                "  sudo ./%(prog)s remove --with-ssl\n\n"
                "  # Запустить настройку с записью всего вывода в лог-файл:\n"
                "  sudo ./%(prog)s setup -l /var/log/drweb_squid_setup.log\n\n"

    )
    parser.add_argument('-v', '--version', action='version', version=f'%(prog)s {__version__}')
    subparsers = parser.add_subparsers(dest='command', required=True, help='Доступные команды')

    # --- Родительские парсеры для общих опций ---
    base_parser = argparse.ArgumentParser(add_help=False, 
                                          epilog="Параметры:\n"
                                                 "-squid-config-dir Явно указать путь к директории конфигурации Squid"
                                                 "--icapd-host      Хост для ICAPD-сокета (по умолч.: 127.0.0.1)"
                                                 "--icapd-port      Порт для ICAPD-сокета (по умолч.: 1344)"
                                                 "--squid-port      Порт для параметра http_port в Squid(по умолч.: 3128)"
                                                 "--with-ssl        Провести настройку squid для разбора HTTPS трафика"
                                                 "-l, --log-file    Сохранять весь вывод в файл журнала"
                                                 "-d, --debug       Включить подробный отладочный вывод"
                                                 "--no-color        Отключить цветной вывод"
                                                 "-y, --yes         Пропустить интерактивные запросы подтверждения"
                                                 )
    base_parser.add_argument('--squid-config-dir', type=str,
                             help='Явно указать путь к директории конфигурации Squid (например, /etc/squid).')
    base_parser.add_argument('-l', '--log-file', default=None, help='Сохранять весь вывод в файл журнала.')
    base_parser.add_argument('-d', '--debug', action='store_true', help='Включить подробный отладочный вывод.')
    base_parser.add_argument('--no-color', action='store_true', help='Отключить цветной вывод.')
    base_parser.add_argument('--with-ssl', dest="with_ssl", default=False, action='store_true',
                               help='Провести настройку squid для разбора HTTPS трафика.')
    base_parser.add_argument('--squid-port', dest="squid_port", default=3128, type=int,
                               help='Порт для параметра http_port в Squid(по умолч.: 3128)')
    interactive_parser = argparse.ArgumentParser(add_help=False)
    interactive_parser.add_argument('-y', '--yes', action='store_true',
                                    help='Пропустить интерактивные запросы подтверждения.')

    # --- Суб-парсер для команды 'setup' ---
    parser_icapd = subparsers.add_parser('setup', parents=[base_parser],
                                          help='Настройка интеграции через ICAPD.')
    parser_icapd.add_argument('--icapd-host', dest="icapd_host", default='127.0.0.1',
                               help='Хост для ICAPD-сокета (по умолч.: 127.0.0.1).')
    parser_icapd.add_argument('--icapd-port', dest="icapd_port", default=1344, type=int,
                               help='Порт для ICAPD-сокета (по умолч.: 1344).')
    # --- Суб-парсер для команды 'remove' ---
    subparsers.add_parser('remove', parents=[base_parser, interactive_parser],
                          help='Удаление ранее сделанных настроек.')
    args = parser.parse_args()
    logger.reconfigure(debug_mode=args.debug, color_enabled=not args.no_color, log_file=args.log_file)
    try:
        check_root()
        check_drweb_license()
        mode = check_drweb_standalone_mode()
        squid_config_dir = find_squid_config_dir(args)
        version = check_squid_version(args)
        # Вызов соответствующего обработчика
        if args.command == 'setup':
            handle_setup(args, squid_config_dir, version, mode)
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
