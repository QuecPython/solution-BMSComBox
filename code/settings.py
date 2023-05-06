# Copyright (c) Quectel Wireless Solution, Co., Ltd.All Rights Reserved.
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

#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@file      :settings.py
@author    :Jack Sun (jack.sun@quectel.com)
@brief     :<description>
@version   :1.0.0
@date      :2022-09-27 15:19:03
@copyright :Copyright (c) 2022
"""

import uos
import ure
import ql_fs
import ujson
import modem
import _thread
from machine import UART,Pin
from usr.modules import option_lock


PROJECT_NAME = "QuecPython-Tracker"

PROJECT_VERSION = "2.1.0"

DEVICE_FIRMWARE_NAME = uos.uname()[0].split("=")[1]

DEVICE_FIRMWARE_VERSION = modem.getDevFwVersion()

_settings_lock = _thread.allocate_lock()


class QuecCloudConfig:
    pk = "p11oja"
    ps = "VVhsaC9VQUx5NEV5"
    dk = "999999999"
    ds = "fdb1406dc6b6c85956871e14c49c515e"
    mode = 1
    server = "iot-south.quectel.com:1883"
    life_time = 120
    fw_name = DEVICE_FIRMWARE_NAME
    fw_version = DEVICE_FIRMWARE_VERSION


class LocConfig:

    class _gps_mode:
        none = 0x0
        internal = 0x1
        external = 0x2

    class _loc_method:
        none = 0x0
        gps = 0x1
        cell = 0x2
        wifi = 0x4
        all = 0x7

    profile_idx = 1

    gps_cfg = {
        "UARTn": UART.UART1,
        "buadrate": 115200,
        "databits": 8,
        "parity": 0,
        "stopbits": 1,
        "flowctl": 0,
        "gps_mode": _gps_mode.internal,
        # "nmea": 0b010111,
        "nmea": 0b000111,
        "PowerPin": None,
        "StandbyPin": None,
        "BackupPin": None,
    }

    loc_method = _loc_method.gps
    


class UserConfig:

    class _bms_protocol:
        sif = 0x0
        rs485 = 0x1

    debug = True

    log_level = "DEBUG"

    checknet_timeout = 60

    sif_gpio_pin = 32 #测试IO 为25，实际电路为32

    phone_num = ""

    fota = True

    sota = True

    bms_protocol = _bms_protocol.rs485

    reportTimes = 60

    rs485_config = {
        "UARTn": UART.UART2,
        "buadrate": 9600,
        "databits": 8,
        "parity": 0,
        "stopbits": 1,
        "flowctl": 0,
        "rs485_pin": Pin.GPIO30,
    }


class Settings:

    def __init__(self, settings_file="/usr/bms_box_settings.json"):
        self.settings_file = settings_file
        self.current_settings = {}
        self.init()

    def __init_config(self):
        try:
            # CloudConfig config
            self.current_settings["quec_cloud_cfg"] = {k: v for k, v in QuecCloudConfig.__dict__.items() if not k.startswith("_")}

            # LocConfig config
            self.current_settings["loc_cfg"] = {k: v for k, v in LocConfig.__dict__.items() if not k.startswith("_")}

            # UserConfig config
            self.current_settings["user_cfg"] = {k: v for k, v in UserConfig.__dict__.items() if not k.startswith("_")}
            return True
        except:
            return False

    def __read_config(self):
        if ql_fs.path_exists(self.settings_file):
            with open(self.settings_file, "r") as f:
                self.current_settings = ujson.load(f)
                return True
        return False

    def __set_config(self, mode, opt, val):
        if mode == "user_cfg":
            if opt == "reportTimes":
                if not isinstance(val, int):
                    return False
                self.current_settings[mode][opt] = val
                return True
        elif mode == "loc_cfg":
            if opt == "loc_method":
                if not isinstance(val, int):
                    return False
                if val > LocConfig._loc_method.all:
                    return False
                self.current_settings[mode][opt] = val
                return True
        elif mode == "quec_cloud_cfg":
            if opt == "life_time":
                if not isinstance(val, int):
                    return False
                self.current_settings[mode][opt] = val
                return True
            elif opt in ("pk", "ps", "dk", "ds", "server"):
                if not isinstance(val, str):
                    return False
                self.current_settings[mode][opt] = val
                return True
        return False

    def __save_config(self):
        try:
            with open(self.settings_file, "w") as f:
                ujson.dump(self.current_settings, f)
            return True
        except:
            return False

    def __remove_config(self):
        try:
            uos.remove(self.settings_file)
            return True
        except:
            return False

    def __get_config(self):
        return self.current_settings

    @option_lock(_settings_lock)
    def init(self):
        if self.__read_config() is False:
            if self.__init_config():
                return self.__save_config()
        return False

    @option_lock(_settings_lock)
    def get(self):
        return self.__get_config()

    @option_lock(_settings_lock)
    def set(self, mode, opt, val):
        return self.__set_config(mode, opt, val)

    @option_lock(_settings_lock)
    def save(self):
        return self.__save_config()

    @option_lock(_settings_lock)
    def reset(self):
        if self.__remove_config():
            if self.__init_config():
                return self.__save_config()
        return False
