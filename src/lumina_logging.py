# -*- coding: utf-8 -*-
"""
@brief Lumina 统一日志配置模块。
@note 打包后优先写入 Lumina.exe 同目录，失败时回退到当前用户本地应用数据目录。
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


APPLICATION_NAME = "Lumina"
LOG_FILE_NAME = "lumina.log"
# 单个日志文件最大字节数，单位为字节。
LOG_MAX_BYTES = 20 * 1024 * 1024
LOG_BACKUP_COUNT = 5
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_default_log_directory() -> Path:
    """
    @brief 获取默认日志目录。
    @return Path 默认日志目录路径。
    @note 打包环境优先返回 exe 同目录下的 logs，源码环境使用 LOCALAPPDATA。
    """

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "logs"

    return get_fallback_log_directory()


def get_fallback_log_directory() -> Path:
    """
    @brief 获取日志回退目录。
    @return Path 日志回退目录路径。
    @note Windows 下优先使用 LOCALAPPDATA，其他情况下回退到用户主目录。
    """

    local_app_data = os.environ.get("LOCALAPPDATA")

    if local_app_data:
        return Path(local_app_data) / APPLICATION_NAME / "logs"

    return Path.home() / f".{APPLICATION_NAME.lower()}" / "logs"


def create_rotating_file_handler(
    log_file_path: Path,
    level_value: int,
) -> RotatingFileHandler:
    """
    @brief 创建 Lumina 文件日志处理器。
    @param log_file_path 日志文件路径。
    @param level_value 日志等级。
    @return RotatingFileHandler 文件日志处理器。
    """

    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler._lumina_file_handler = True
    file_handler.setLevel(level_value)
    file_handler.setFormatter(
        logging.Formatter(
            fmt=LOG_FORMAT,
            datefmt=LOG_DATE_FORMAT,
        )
    )
    return file_handler


def parse_log_level(log_level: str | int | None) -> int:
    """
    @brief 将命令行日志等级转换为 logging 模块使用的整数等级。
    @param log_level 日志等级文本或整数。
    @return int logging 模块日志等级。
    """

    if isinstance(log_level, int):
        return log_level

    if log_level is None:
        return logging.INFO

    level_name = str(log_level).strip().upper()

    if not level_name:
        return logging.INFO

    level_value = getattr(logging, level_name, None)

    if isinstance(level_value, int):
        return level_value

    raise ValueError(f"未知日志等级: {log_level}")


def configure_lumina_logging(
    log_dir: str | os.PathLike[str] | None = None,
    log_level: str | int | None = None,
) -> Path:
    """
    @brief 配置 Lumina 文件日志。
    @param log_dir 用户指定的日志目录；为 None 时使用默认目录。
    @param log_level 日志等级。
    @return Path 当前日志文件路径。
    @note 单个日志文件达到 20MB 后自动轮转，最多保留 5 个历史文件。
    """

    root_logger = logging.getLogger()
    level_value = parse_log_level(log_level)
    candidate_log_dirs: list[Path] = []

    if log_dir is not None:
        candidate_log_dirs.append(Path(log_dir))
    else:
        candidate_log_dirs.append(get_default_log_directory())
        fallback_log_dir = get_fallback_log_directory()

        if fallback_log_dir not in candidate_log_dirs:
            candidate_log_dirs.append(fallback_log_dir)

    for handler in list(root_logger.handlers):
        if getattr(handler, "_lumina_file_handler", False):
            root_logger.removeHandler(handler)
            handler.close()

    last_error: Exception | None = None

    for resolved_log_dir in candidate_log_dirs:
        try:
            resolved_log_dir.mkdir(parents=True, exist_ok=True)
            log_file_path = resolved_log_dir / LOG_FILE_NAME
            file_handler = create_rotating_file_handler(
                log_file_path,
                level_value,
            )
            root_logger.addHandler(file_handler)
            break
        except OSError as error:
            last_error = error
    else:
        raise RuntimeError("无法创建 Lumina 日志文件。") from last_error

    root_logger.setLevel(level_value)

    return log_file_path


def add_logging_arguments(parser: object) -> None:
    """
    @brief 为 argparse 解析器添加通用日志参数。
    @param parser argparse.ArgumentParser 对象。
    @return None
    """

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=[
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ],
        help="日志等级，默认值为 INFO。",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="日志目录，打包后默认写入 Lumina.exe 同目录下的 logs。",
    )


def log_and_print(
    logger: logging.Logger,
    level: int,
    message: str,
) -> None:
    """
    @brief 同时输出到控制台并写入日志。
    @param logger 日志对象。
    @param level 日志等级。
    @param message 输出文本。
    @return None
    """

    if sys.stdout is not None:
        try:
            print(message)
        except Exception:
            pass

    logger.log(level, message)
