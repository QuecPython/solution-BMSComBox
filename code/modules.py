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
@file      :modules.py
@author    :Jack Sun (jack.sun@quectel.com)
@brief     :<description>
@version   :1.0.0
@date      :2022-09-26 18:50:20
@copyright :Copyright (c) 2022
"""

import pm
import usys
import ujson
import utime
import _thread
import osTimer

from misc import Power, ADC
from machine import Pin, I2C

from usr.logging import Logger

try:
    from machine import RTC
except ImportError:
    RTC = None

log = Logger(__name__)

_history_lock = _thread.allocate_lock()

BATTERY_OCV_TABLE = {
    "nix_coy_mnzo2": {
        55: {
            4152: 100, 4083: 95, 4023: 90, 3967: 85, 3915: 80, 3864: 75, 3816: 70, 3773: 65, 3737: 60, 3685: 55,
            3656: 50, 3638: 45, 3625: 40, 3612: 35, 3596: 30, 3564: 25, 3534: 20, 3492: 15, 3457: 10, 3410: 5, 3380: 0,
        },
        20: {
            4143: 100, 4079: 95, 4023: 90, 3972: 85, 3923: 80, 3876: 75, 3831: 70, 3790: 65, 3754: 60, 3720: 55,
            3680: 50, 3652: 45, 3634: 40, 3621: 35, 3608: 30, 3595: 25, 3579: 20, 3548: 15, 3511: 10, 3468: 5, 3430: 0,
        },
        0: {
            4147: 100, 4089: 95, 4038: 90, 3990: 85, 3944: 80, 3899: 75, 3853: 70, 3811: 65, 3774: 60, 3741: 55,
            3708: 50, 3675: 45, 3651: 40, 3633: 35, 3620: 30, 3608: 25, 3597: 20, 3585: 15, 3571: 10, 3550: 5, 3500: 0,
        },
    },
}

LOW_ENERGY_METHOD = ("NULL", "PM", "POWERDOWN")


def option_lock(thread_lock):
    def function_lock(func):
        def wrapperd_fun(*args, **kwargs):
            with thread_lock:
                return func(*args, **kwargs)
        return wrapperd_fun
    return function_lock


class Battery(object):
    def __init__(self, adc_args=None, chrg_gpion=None, stdby_gpion=None, battery_ocv="nix_coy_mnzo2"):
        self.__energy = 100
        self.__temp = 20

        self.__adc = ADC() if adc_args else None
        self.__adc_num, self.__adc_period, self.__factor = adc_args if adc_args else (None, None, None)

        self.__charge_status = -1
        self.__chrg_gpio = Pin(chrg_gpion, Pin.IN, Pin.PULL_DISABLE) if chrg_gpion else None
        self.__stdby_gpio = Pin(stdby_gpion, Pin.IN, Pin.PULL_DISABLE) if stdby_gpion else None

        if not BATTERY_OCV_TABLE.get(battery_ocv):
            raise TypeError("Battery OCV %s is not support." % battery_ocv)
        self.__battery_ocv = battery_ocv

    def __init_charge_status(self):
        if self.__chrg_gpio and self.__stdby_gpio:
            chrg_level = self.__chrg_gpio.read()
            stdby_level = self.__stdby_gpio.read()
            if chrg_level == 1 and stdby_level == 1:
                self.__charge_status = 0
            elif chrg_level == 0 and stdby_level == 1:
                self.__charge_status = 1
            elif chrg_level == 1 and stdby_level == 0:
                self.__charge_status = 2
            else:
                self.__charge_status = -1

    def __get_adc_vbatt(self):
        self.__adc.open()
        utime.sleep_ms(self.__adc_period)
        adc_list = list()
        for i in range(self.__adc_period):
            adc_list.append(self.__adc.read(self.__adc_num))
            utime.sleep_ms(self.__adc_period)
        adc_list.remove(min(adc_list))
        adc_list.remove(max(adc_list))
        adc_value = int(sum(adc_list) / len(adc_list))
        self.__adc.close()
        vbatt_value = adc_value * (self.__factor + 1)
        return vbatt_value

    def __get_power_vbatt(self):
        return int(sum([Power.getVbatt() for i in range(100)]) / 100)

    def __get_soc_by_temp(self, temp):
        if BATTERY_OCV_TABLE[self.__battery_ocv].get(temp):
            _voltage = self.voltage
            volts = sorted(BATTERY_OCV_TABLE[self.__battery_ocv][temp].keys(), reverse=True)
            pre_volt = 0
            volt_not_under = 0
            for volt in volts:
                if _voltage > volt:
                    volt_not_under = 1
                    soc1 = BATTERY_OCV_TABLE[self.__battery_ocv][temp].get(volt, 0)
                    soc2 = BATTERY_OCV_TABLE[self.__battery_ocv][temp].get(pre_volt, 0)
                    break
                else:
                    pre_volt = volt
            if pre_volt == 0:
                return soc1
            elif volt_not_under == 0:
                return 0
            else:
                return soc2 - (soc2 - soc1) * (pre_volt - _voltage) // (pre_volt - volt)
        return -1

    def __get_soc(self):
        if self.__temp > 30:
            return self.__get_soc_by_temp(55)
        elif self.__temp < 10:
            return self.__get_soc_by_temp(0)
        else:
            return self.__get_soc_by_temp(20)

    def set_temp(self, temp):
        if isinstance(temp, int) or isinstance(temp, float):
            self.__temp = temp
            return True
        return False

    @property
    def charge_status(self):
        self.__init_charge_status()
        return self.__charge_status

    @property
    def voltage(self):
        if self.__adc:
            return self.__get_adc_vbatt()
        else:
            return self.__get_power_vbatt()

    @property
    def energy(self):
        return self.__get_soc()


class History:

    def __init__(self, history_file="/usr/tracker_data.hist", max_size=0x4000):
        self.__history = history_file
        self.__max_size = max_size

    def __read(self):
        res = {"data": []}
        try:
            with open(self.__history, "rb") as f:
                hist_data = ujson.load(f)
                if isinstance(hist_data, dict):
                    res["data"] = hist_data.get("data", [])
        except Exception as e:
            usys.print_exception(e)
        return res

    def __write(self, data):
        try:
            with open(self.__history, "wb") as f:
                ujson.dump(data, f)
            return True
        except Exception as e:
            usys.print_exception(e)
        return False

    @option_lock(_history_lock)
    def read(self):
        res = self.__read()
        self.__write({"data": []})
        return res

    @option_lock(_history_lock)
    def write(self, data):
        res = self.__read()
        res["data"].extend(data)
        while len(ujson.dumps(res)) > self.__max_size:
            res["data"].pop()
        return self.__write(res)


class LowEnergyManage:

    def __init__(self, period=60, method="PM"):
        self.__timer = RTC() if RTC else osTimer()
        self.__period = period
        self.__lpm_fd = None
        self.__low_energy_method = method
        self.__pm_lock_name = "low_energy_pm_lock"
        self.__callback = None

    def __callback_thread(self):
        if self.__low_energy_method == "PM":
            self.__pm_init()
            wlk_res = pm.wakelock_lock(self.__lpm_fd)
            log.debug("pm.wakelock_lock %s." % ("Success" if wlk_res == 0 else "Falied"))

        if self.__callback:
            self.__callback(self.__low_energy_method)

        if self.__low_energy_method == "PM":
            wulk_res = pm.wakelock_unlock(self.__lpm_fd)
            log.debug("pm.wakelock_unlock %s." % ("Success" if wulk_res == 0 else "Falied"))

    def __timer_callback(self, args):
        _thread.start_new_thread(self.__callback_thread, ())

    def __rtc_enable(self, enable):
        return True if self.__timer.enable_alarm(enable) == 0 else False

    def __rtc_start(self):
        self.__rtc_enable(0)
        atime = utime.localtime(utime.mktime(utime.localtime()) + self.__period)
        alarm_time = [atime[0], atime[1], atime[2], atime[6], atime[3], atime[4], atime[5], 0]
        if self.__timer.register_callback(self.__timer_callback) == 0:
            if self.__timer.set_alarm(alarm_time) == 0:
                return self.__rtc_enable(1)
        return False

    def __rtc_stop(self):
        return self.__rtc_enable(0)

    def __ostimer_start(self):
        return True if self.__timer.start(self.__period * 1000, 0, self.__timer_callback) == 0 else False

    def __ostimer_stop(self):
        return True if self.__timer.stop() == 0 else False

    def __pm_init(self):
        pm.autosleep(1)
        if not self.__lpm_fd:
            self.__lpm_fd = pm.create_wakelock(self.__pm_lock_name, len(self.__pm_lock_name))

    def set_period(self, seconds=0):
        if isinstance(seconds, int) and seconds > 0:
            self.__period = seconds
            return True
        return False

    def set_method(self, method):
        if method in LOW_ENERGY_METHOD:
            if RTC is None and method == "POWERDOWN":
                return False
            self.__low_energy_method = method
            return True
        return False

    def set_callback(self, callback):
        if callable(callback):
            self.__callback = callback
            return True
        return False

    def start(self):
        return self.__rtc_start() if RTC else self.__ostimer_start()

    def stop(self):
        return self.__rtc_stop() if RTC else self.__ostimer_stop()
