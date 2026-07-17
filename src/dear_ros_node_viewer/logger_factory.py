# Copyright 2023 iwatake2222
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Logger Factory
"""
import logging
import os


class LoggerFactory():
  '''Logger Factory'''
  level: int = logging.DEBUG
  log_filename: str = None
  # Loggers created so far, so that config() can retroactively attach a file
  # handler to them. Modules create their logger at import time (before main()
  # calls config()), so without this the file handler would miss them.
  _created_loggers: list = []

  @classmethod
  def create(cls, name) -> logging.Logger:
    '''Create logger'''
    logger = logging.getLogger(name)
    logger.setLevel(cls.level)
    stream_handler = logging .StreamHandler()
    stream_handler.setLevel(cls.level)
    handler_format = logging.Formatter('[%(levelname)-7s][%(filename)s:%(lineno)s] %(message)s')
    stream_handler.setFormatter(handler_format)
    logger.addHandler(stream_handler)
    if cls.log_filename:
      cls._add_file_handler(logger)
    if logger not in cls._created_loggers:
      cls._created_loggers.append(logger)
    return logger

  @classmethod
  def _add_file_handler(cls, logger) -> None:
    '''Attach a file handler to the logger (skip if one already exists).'''
    if not cls.log_filename:
      return
    if any(isinstance(h, logging.FileHandler) and
           getattr(h, 'baseFilename', None) == os.path.abspath(cls.log_filename)
           for h in logger.handlers):
      return
    file_handler = logging.FileHandler(cls.log_filename)
    file_handler.setLevel(cls.level)
    handler_format = logging.Formatter(
      '[%(asctime)s][%(levelname)-7s][%(filename)s:%(lineno)s] %(message)s')
    file_handler.setFormatter(handler_format)
    logger.addHandler(file_handler)

  @classmethod
  def config(cls, level, log_filename) -> None:
    '''Config

    Sets the log level and (optionally) a file to also write logs to.
    The file handler is attached to every logger created so far as well as
    to loggers created afterwards, so calling this from main() still captures
    module-level loggers created at import time.
    '''
    LoggerFactory.level = level
    LoggerFactory.log_filename = log_filename
    if log_filename:
      for logger in cls._created_loggers:
        logger.setLevel(level)
        cls._add_file_handler(logger)
