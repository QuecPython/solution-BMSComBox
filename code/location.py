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
@file      :location.py
@author    :Jack Sun (jack.sun@quectel.com)
@brief     :<description>
@version   :1.0.0
@date      :2022-10-10 13:55:52
@copyright :Copyright (c) 2022
"""

import net
import ure
import math
import utime
import _thread
import osTimer
import wifiScan
import cellLocator

from queue import Queue
from machine import Pin, UART

from usr.logging import Logger
from usr.modules import option_lock

try:
    import quecgnss
except ImportError:
    quecgnss = None

log = Logger(__name__)

EE = 0.00669342162296594323
EARTH_RADIUS = 6378.137
M_PI = math.pi

_gps_data_set_lock = _thread.allocate_lock()


def _transformLat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(math.fabs(x))
    ret += (20.0 * math.sin(6.0 * x * M_PI) + 20.0 * math.sin(2.0 * x * M_PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * M_PI) + 40.0 * math.sin(y / 3.0 * M_PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * M_PI) + 320 * math.sin(y * M_PI / 30.0)) * 2.0 / 3.0
    return ret


def _transformLon(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(math.fabs(x))
    ret += (20.0 * math.sin(6.0 * x * M_PI) + 20.0 * math.sin(2.0 * x * M_PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * M_PI) + 40.0 * math.sin(x / 3.0 * M_PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * M_PI) + 300.0 * math.sin(x / 30.0 * M_PI)) * 2.0 / 3.0
    return ret


def WGS84ToGCJ02(lon, lat):
    dLat = _transformLat(lon - 105.0, lat - 35.0)
    dLon = _transformLon(lon - 105.0, lat - 35.0)
    radLat = lat / 180.0 * M_PI
    magic = math.sin(radLat)
    magic = 1 - magic * magic * EE
    sqrtMagic = math.sqrt(magic)

    dLat = (dLat * 180.0) / ((EARTH_RADIUS * 1000 * (1 - EE)) / (magic * sqrtMagic) * M_PI)
    dLon = (dLon * 180.0) / (EARTH_RADIUS * 1000 / sqrtMagic * math.cos(radLat) * M_PI)
    lon02 = lon + dLon
    lat02 = lat + dLat

    return lon02, lat02


class NMEAParse:

    def __init__(self):
        self.__gps_data = ""

    def __parse(self, nmea):
        return tuple(nmea[1:].split("*")[0].split(",")) if nmea else ()

    def set_gps_data(self, gps_data):
        self.__gps_data = gps_data

    @property
    def GxRMC(self):
        if self.__gps_data:
            rmc_re = ure.search(
                r"\$G[NP]RMC,\d*\.*\d*,*[AV],*\d*\.*\d*,*[NS],*\d*\.*\d*,*[EW],*\d*\.*\d*,*\d*\.*\d*,*\d*,*\d*\.*\d*,*[EW]*,*[ADEN]*,*[SCUV]*\**(\d|\w)*",
                self.__gps_data)
            if rmc_re:
                return rmc_re.group(0)
        return ""

    @property
    def GxGGA(self):
        if self.__gps_data:
            gga_re = ure.search(
                r"\$G[BLPN]GGA,\d*\.*\d*,*\d*\.*\d*,*[NS],*\d*\.*\d*,*[EW],*[0126],*\d*,*\d*\.*\d*,*-*\d*\.*\d*,*M,*-*\d*\.*\d*,*M,*\d*,*\**(\d|\w)*",
                self.__gps_data)
            if gga_re:
                return gga_re.group(0)
        return ""

    @property
    def GxVTG(self):
        if self.__gps_data:
            vtg_re = ure.search(
                r"\$G[NP]VTG,\d*\.*\d*,*T,*\d*\.*\d*,*M,*\d*\.*\d*,*N,*\d*\.*\d*,*K,*[ADEN]*\*(\d|\w)*",
                self.__gps_data)
            if vtg_re:
                return vtg_re.group(0)
        return ""

    @property
    def GxGSV(self):
        if self.__gps_data:
            gsv_re = ure.search(
                r"\$G[NP]GSV,\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*\**(\d|\w)*",
                self.__gps_data)
            if gsv_re:
                return gsv_re.group(0)
        return ""

    @property
    def GxGLL(self):
        if self.__gps_data:
            gll_re = ure.search(
                r"\$G[NP]GLL,\d*\.*\d*,*[NS]*,*\d*\.*\d*,*[EW]*,*\d*\.*\d*,*[AV]*,*[ADEN]*\**(\d|\w)*",
                self.__gps_data)
            if gll_re:
                return gll_re.group(0)

    @property
    def GxGSA(self):
        if self.__gps_data:
            gsa_re = ure.search(
                r"\$G[NP]GSA,[MA]*,*[123]*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*,*\d*\.*\d*,*\d*\.*\d*,*\d*\.*\d*,*(\d|\w)*\**(\d|\w)*",
                self.__gps_data)
            if gsa_re:
                return gsa_re.group(0)

    @property
    def GxRMCData(self):
        return self.__parse(self.GxRMC)

    @property
    def GxGGAData(self):
        return self.__parse(self.GxGGA)

    @property
    def GxGSVData(self):
        return self.__parse(self.GxGSV)

    @property
    def GxGSAData(self):
        return self.__parse(self.GxGSA)

    @property
    def GxVTGData(self):
        return self.__parse(self.GxVTG)

    @property
    def GxGLLData(self):
        return self.__parse(self.GxGLL)


class GPSLowEnergy:

    def __init__(self, PowerPin, StandbyPin, BackupPin):
        self.__PowerPin = PowerPin
        self.__StandbyPin = StandbyPin
        self.__BackupPin = BackupPin
        self.__gps_power_gpio = None
        self.__gps_standby_gpio = None
        self.__gps_backup_gpio = None

    def __power_control(self, method, onoff):
        if method == "power_switch":
            if self.__gps_power_gpio is None:
                self.__gps_power_gpio = Pin(self.__PowerPin, Pin.OUT, Pin.PULL_DISABLE, onoff)
            gpio_obj = self.__gps_power_gpio
        elif method == "standby":
            if self.__gps_standby_gpio is None:
                self.__gps_standby_gpio = Pin(self.__StandbyPin, Pin.OUT, Pin.PULL_DISABLE, onoff)
            gpio_obj = self.__gps_standby_gpio
        elif method == "backup":
            if self.__gps_backup_gpio is None:
                self.__gps_backup_gpio = Pin(self.__BackupPin, Pin.OUT, Pin.PULL_DISABLE, onoff)
            gpio_obj = self.__gps_backup_gpio
        else:
            return False

        if gpio_obj.read() != onoff:
            gpio_obj.write(onoff)
            utime.sleep_ms(50)
            if gpio_obj.read() != onoff:
                return False
        return True

    def power_switch(self, onoff):
        if self.__PowerPin is not None:
            return self.__power_control("power_switch", onoff)
        return False

    def backup(self, onoff):
        if self.__BackupPin is not None:
            return self.__power_control("backup", onoff)
        return False

    def standby(self, onoff):
        if self.__StandbyPin is not None:
            return self.__power_control("standby", onoff)
        return False


class GPS(GPSLowEnergy):

    __RMC = 0
    __GGA = 1
    __GSV = 2
    __GSA = 3
    __VTG = 4
    __GLL = 5
    __NMEA = 0b010111

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

    def __init__(self, UARTn, buadrate, databits, parity, stopbits, flowctl, gps_mode, nmea, PowerPin, StandbyPin, BackupPin):
        super().__init__(PowerPin, StandbyPin, BackupPin)
        self.__UARTn = UARTn
        self.__buadrate = buadrate
        self.__databits = databits
        self.__parity = parity
        self.__stopbits = stopbits
        self.__flowctl = flowctl
        self.__gps_mode = gps_mode
        if nmea:
            self.__NMEA = nmea

        self.__external_obj = None
        self.__internal_obj = quecgnss
        self.__nmea_parse = NMEAParse()

        self.__external_retrieve_queue = None
        self.__queue_size = 2
        self.__first_break = 0
        self.__break = 0
        self.__gps_data = ""
        self.__rmc_data = ""
        self.__gga_data = ""
        self.__vtg_data = ""
        self.__gsv_data = ""

        self.__gps_timer = osTimer()
        self.__gps_data_check_timer = osTimer()

        if self.__gps_mode == self._gps_mode.external:
            self.__external_init()
        elif self.__gps_mode == self._gps_mode.internal:
            self.__internal_init()

    @option_lock(_gps_data_set_lock)
    def __set_gps_data(self, gps_data):
        self.__gps_data = gps_data

    @option_lock(_gps_data_set_lock)
    def __get_gps_data(self):
        return self.__gps_data

    def __reverse_gps_data(self, this_gps_data):
        log.debug("this_gps_data: \n%s" % this_gps_data)
        CRLF = "\r\n"
        if this_gps_data:
            _gps_data = self.__get_gps_data()
            if _gps_data:
                _gps_data = CRLF.join(_gps_data.split(CRLF)[::-1])
            _gps_data += this_gps_data.strip().replace("\r", "").replace("\n", "").replace("$", CRLF + "$")
            _gps_data = CRLF.join(_gps_data.split(CRLF)[::-1])
            self.__set_gps_data(_gps_data)

    def __gps_timer_callback(self, args):
        self.__break = 1
        if self.__external_retrieve_queue is not None:
            self.__external_retrieve_queue.put(False)

    def __gps_data_check_callback(self, args):
        if not self.__check_gps_valid():
            self.__gps_nmea_data_clean()

    def __external_init(self):
        self.__external_retrieve_queue = Queue(maxsize=self.__queue_size)

    def __external_open(self):
        self.power_switch(1)
        self.__external_obj = UART(
            self.__UARTn,
            self.__buadrate,
            self.__databits,
            self.__parity,
            self.__stopbits,
            self.__flowctl
        )
        self.__external_obj.set_callback(self.__external_retrieve_cb)

    def __external_close(self):
        self.__external_obj.close()

    def __external_retrieve_cb(self, args):
        if self.__external_retrieve_queue.size() >= self.__queue_size:
            self.__external_retrieve_queue.get()
        self.__external_retrieve_queue.put(True)

    def __internal_init(self):
        if self.__internal_obj:
            if self.__internal_obj.init() != 0:
                log.error("GNSS INIT Failed.")
            else:
                log.debug("GNSS INIT Success.")
        else:
            log.error("Module quecgnss Import Error.")

    def __internal_open(self):
        return True if self.__internal_obj.gnssEnable(1) == 0 else False

    def __internal_close(self):
        return True if self.__internal_obj.gnssEnable(0) == 0 else False

    def __nmea_statement_exist(self, nmea_item):
        return (self.__NMEA & (0b1 << nmea_item)) >> nmea_item

    def __gps_nmea_data_clean(self):
        self.__set_gps_data("")
        self.__rmc_data = ""
        self.__gga_data = ""
        self.__gsv_data = ""
        self.__gsa_data = ""
        self.__vtg_data = ""
        self.__gll_data = ""

    def __check_gps_valid(self):
        self.__nmea_parse.set_gps_data(self.__get_gps_data())
        if not self.__rmc_data:
            self.__rmc_data = self.__nmea_parse.GxRMC
        _rmc_info = self.__nmea_parse.GxRMCData
        loc_status = _rmc_info[2] if _rmc_info else "V"

        if self.__rmc_data and loc_status == "A":
            if self.__nmea_statement_exist(self.__GGA) and not self.__gga_data:
                self.__gga_data = self.__nmea_parse.GxGGA
            if self.__nmea_statement_exist(self.__GSV) and not self.__gsv_data:
                self.__gsv_data = self.__nmea_parse.GxGSV
            if self.__nmea_statement_exist(self.__GSA) and not self.__gsa_data:
                self.__gsa_data = self.__nmea_parse.GxGSA
            if self.__nmea_statement_exist(self.__VTG) and not self.__vtg_data:
                self.__vtg_data = self.__nmea_parse.GxVTG
            if self.__nmea_statement_exist(self.__GLL) and not self.__gll_data:
                self.__gll_data = self.__nmea_parse.GxGLL

            if self.__nmea_statement_exist(self.__GGA) and not self.__gga_data:
                return False
            if self.__nmea_statement_exist(self.__GSV) and not self.__gsv_data:
                return False
            if self.__nmea_statement_exist(self.__GSA) and not self.__gsa_data:
                return False
            if self.__nmea_statement_exist(self.__VTG) and not self.__vtg_data:
                return False
            if self.__nmea_statement_exist(self.__GLL) and not self.__gll_data:
                return False
            return True

        return False

    def __external_read(self):
        #self.__external_open()
        log.debug("__external_read start")

        while self.__break == 0:
            self.__gps_timer.start(50, 0, self.__gps_timer_callback)
            signal = self.__external_retrieve_queue.get()
            log.debug("[first] signal: %s" % signal)
            if signal:
                to_read = self.__external_obj.any()
                log.debug("[first] to_read: %s" % to_read)
                if to_read > 0:
                    self.__set_gps_data(self.__external_obj.read(to_read).decode())
            self.__gps_timer.stop()
        self.__break = 0

        self.__gps_nmea_data_clean()
        self.__gps_data_check_timer.start(2000, 1, self.__gps_data_check_callback)
        cycle = 0
        while self.__break == 0:
            self.__gps_timer.start(1500, 0, self.__gps_timer_callback)
            signal = self.__external_retrieve_queue.get()
            log.debug("[second] signal: %s" % signal)
            if signal:
                to_read = self.__external_obj.any()
                log.debug("[second] to_read: %s" % to_read)
                if to_read > 0:
                    self.__reverse_gps_data(self.__external_obj.read(to_read).decode())
                    if self.__check_gps_valid():
                        self.__break = 1

            self.__gps_timer.stop()
            cycle += 1
            if cycle >= self.__retry:
                self.__break = 1
            if self.__break != 1:
                utime.sleep(1)
        self.__gps_data_check_timer.stop()
        self.__break = 0

        # To check GPS data is usable or not.
        self.__gps_data_check_callback(None)
        #self.__external_close()
        log.debug("__external_read data: %s" % self.__get_gps_data())
        return self.__get_gps_data()

    def __internal_read(self):
        log.debug("__internal_read start.")
        #self.__internal_open()
        while self.__break == 0:
            gnss_data = quecgnss.read(1024)
            if gnss_data[0] == 0:
                self.__break = 1
        self.__break = 0
        self.__gps_nmea_data_clean()
        self.__gps_data_check_timer.start(2000, 1, self.__gps_data_check_callback)
        cycle = 0
        while self.__break == 0:
            gnss_data = quecgnss.read(1024)
            if gnss_data and gnss_data[1]:
                this_gps_data = gnss_data[1].decode() if len(gnss_data) > 1 and gnss_data[1] else ""
                self.__reverse_gps_data(this_gps_data)
                _gps_valid = self.__check_gps_valid()
                log.debug("_gps_valid: %s" % _gps_valid)
                if _gps_valid:
                    self.__break = 1
            cycle += 1
            if cycle >= self.__retry:
                if self.__break != 1:
                    self.__break = 1
            if self.__break != 1:
                utime.sleep(1)
        self.__gps_data_check_timer.stop()
        self.__break = 0
        self.__gps_data_check_callback(None)
        #self.__internal_close()
        return self.__get_gps_data()

    def read(self, retry=30):
        self.__retry = retry
        gps_data = ""
        if self.__gps_mode == self._gps_mode.external:
            gps_data = self.__external_read()
        elif self.__gps_mode == self._gps_mode.internal:
            gps_data = self.__internal_read()

        res = 0 if gps_data else -1
        return (res, gps_data)


    def close(self):
        if self.__gps_mode == self._gps_mode.external:
            self.__external_close()
        elif self.__gps_mode == self._gps_mode.internal:
            self.__internal_close()

    def open(self):
        if self.__gps_mode == self._gps_mode.external:
            self.__external_open()
        elif self.__gps_mode == self._gps_mode.internal:
            self.__internal_open()