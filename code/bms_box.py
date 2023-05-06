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
@file      :bms_box.py
@author    :Elian Wang (elian.wang@quectel.com)
@brief     :<description>
@version   :1.0.0
@date      :2022-10-22 14:22:54
@copyright :Copyright (c) 2022
"""
import gc
import pm
import net
import sif
import usys
import utime
import modem
import _thread
import dataCall
import checkNet
from misc import Power
from usr.logging import Logger
from usr.quecthing import QuecObjectModel, QuecThing, QuecOTA
from usr.xingheng_sif_protocol import XinghengSifProtocol
from usr.xingheng_rs485_protocol import XinghengRs485Protocol
from usr.location import NMEAParse, GPS
from usr.settings import Settings, PROJECT_NAME, PROJECT_VERSION, DEVICE_FIRMWARE_NAME, DEVICE_FIRMWARE_VERSION

log = Logger(__name__)

LOWENERGYMAP = {
    "PM": ["EC200U", "EC600N", "EC800G", "EC800M"],
    "POWERDOWN": ["EC200U"],
}


class BmsBox:

    def __init__(self):
        self.__settings = None
        self.__gps = None
        self.__nmea_parse = None
        self.__quec_ota = None
        self.__quec_cloud = None
        self.__quec_objmodel = None
        self.__bms_protocol = None
        self.__lpm_fd = None
        self.__pm_lock_name = "low_energy_pm_lock"
        self.__enter_low_power = False
        self.__last_fault_state = False
        self.__data_report_start_timestamp = utime.time()
        self.__report_period_time = 60
        

    def __format_loc_method(self, data):
        loc_method = "%04d" % int(bin(data)[2:])
        _loc_method = {
            "gps": bool(int(loc_method[-1])),
            "cell": bool(int(loc_method[-2])),
            "wifi": bool(int(loc_method[-3])),
        }
        return _loc_method

    def __get_local_time(self):
        return str(utime.mktime(utime.localtime()) * 1000)

    def __get_net_status(self):
        checknet_timeout = self.__settings.get()["user_cfg"]["checknet_timeout"]
        checknet = checkNet.CheckNetwork(PROJECT_NAME, PROJECT_VERSION)
        check_res = checknet.wait_network_connected(checknet_timeout)
        log.debug("DeviceCheck.net res: %s" % str(check_res))
        return check_res

    def __net_datacall(self):
        data_call_info = dataCall.getInfo(1, 0)
        return True if isinstance(data_call_info, tuple) and data_call_info[2][0] == 1 else False

    def __net_connect(self):
        if not self.__net_datacall():
            net.setModemFun(4)
            utime.sleep_ms(200)
            net.setModemFun(1)
            count = 0
            while True:
                if self.__net_datacall():
                    break
                count += 1
                if count > 10:
                    break
                utime.sleep(count)

    def __get_location(self):
        res = {}
        loc_method = self.__settings.get()["loc_cfg"]["loc_method"]
        if loc_method & self.__gps._loc_method.gps:
            gps_res = self.__gps.read(retry=30)
            if gps_res[0] == 0:
                self.__nmea_parse.set_gps_data(gps_res[1])
                res['gps'] = [self.__nmea_parse.GxRMC, self.__nmea_parse.GxGGA, self.__nmea_parse.GxVTG]
                return res
        return res

    def __init_alarm_data(self):
        return self.__bms_protocol.get_alarm_data()

    def __report_cell_volt_data(self):
        res = False
        data = []
        i = 0
        print("battery_serial_num:",self.__bms_protocol.__battery_serial_num)
        print("cell_volt len:", len(self.__bms_protocol.__cell_volt))
        if self.__bms_protocol.__battery_serial_num == 0:
            return False
        try:
            while i < self.__bms_protocol.__battery_serial_num:
                data.append({1: i+1, 2: self.__bms_protocol.__cell_volt[i]})
                i += 1
            _data = {27: data}
            res = self.__quec_cloud.objmodel_report(_data)
            log.debug("cell volt report %s." % ("success" if res else "falied"))
        except Exception as e:
            usys.print_exception(e)
        return res

    def __init_report_data(self):
        _data = {}
        _data.update(self.__get_location())
        _data.update(self.__bms_protocol.get_report_data())
        _data.update({"reportTimes": self.__settings.get()["user_cfg"]["reportTimes"]})
        return _data

    def __data_report(self, data):
        res = False
        if self.__cloud_conn_status():
            for _method in ["gps", "cell"]:
                if data.get(_method):
                    _res = self.__quec_cloud.loc_report(data[_method], mode=_method)
                    log.debug("Quec %s report %s" % (_method, "success" if _res else "falied"))
                    if _res:
                        data.pop(_method)
            _data = self.__quec_objmodel.convert_to_server(data)
            log.debug("objmodel_report data: %s" % str(_data))
            res = self.__quec_cloud.objmodel_report(_data)
        log.debug("Quec object model report %s." % ("success" if res else "falied"))
        return res

    def __set_config(self, data):
        _settings = self.__settings.get()
        for k, v in data.items():
            mode = ""
            if k in _settings["user_cfg"].keys():
                mode = "user_cfg"
                res = self.__settings.set(mode, k, v)
            elif k in _settings["loc_cfg"].keys():
                mode = "loc_cfg"
                if k == "loc_method":
                    v = (int(v.get("wifi", 0)) << 2) + (int(v.get("cell", 0)) << 1) + int(v.get("gps", 0))
                res = self.__settings.set(mode, k, v)
            elif k in _settings["quec_cloud_cfg"].keys():
                mode = "quec_cloud_cfg"
                res = self.__settings.set(mode, k, v)
            else:
                log.warn("Key %s is not find in settings. Value: %s" % (k, v))

            if mode:
                log.debug("Settings set %s %s to %s %s" % (mode, k, v, "success" if res else "falied"))
        self.__settings.save()

    def __set_objmodel(self, data):
        data = self.__quec_objmodel.convert_to_client(data)
        log.debug("set_objmodel data: %s" % str(data))
        self.__set_config(data)

    def __query_objmodel(self, data):
        objmodel_codes = [self.__quec_objmodel.id_code.get(i) for i in data if self.__quec_objmodel.id_code.get(i)]
        log.debug("query_objmodel ids: %s, codes: %s" % (str(data, str(objmodel_codes))))
        report_data = self.__init_report_data()
        self.__data_report(report_data)

    def __ota_plain_check(self, target_module, target_version, battery_limit, min_signal_intensity, use_space):
        _settings = self.__settings.get()
        if target_module == DEVICE_FIRMWARE_NAME and _settings["user_cfg"]["fota"] == True:
            source_version = DEVICE_FIRMWARE_VERSION
        elif target_module == PROJECT_NAME and _settings["user_cfg"]["sota"] == True:
            source_version = PROJECT_VERSION
        else:
            return
        if target_version != source_version:
            self.__quec_cloud.ota_action(action=1)

    def __ota(self, errcode, data):
        if errcode == 10700 and data:
            data = eval(data)
            target_module = data[0]
            # source_version = data[1]
            target_version = data[2]
            battery_limit = data[3]
            min_signal_intensity = data[4]
            use_space = data[5]
            self.__ota_plain_check(target_module, target_version, battery_limit, min_signal_intensity, use_space)
        elif errcode == 10701:
            data = eval(data)
            target_module = data[0]
            length = data[1]
            md5 = data[2]
            self.__set_ota_status(None, None, 2)
            self.__quec_ota.set_ota_info(length, md5)
        elif errcode == 10702:
            self.__set_ota_status(None, None, 2)
        elif errcode == 10703:
            data = eval(data)
            target_module = data[0]
            length = data[1]
            start_addr = data[2]
            piece_length = data[3]
            self.__set_ota_status(None, None, 2)
            self.__quec_ota.start_ota(start_addr, piece_length)
        elif errcode == 10704:
            self.__set_ota_status(None, None, 3)
        elif errcode == 10705:
            self.__set_ota_status(None, None, 4)
        elif errcode == 10706:
            self.__set_ota_status(None, None, 4)

    def __cloud_conn_status(self):
        if not self.__quec_cloud.status:
            self.__net_connect()
        if not self.__quec_cloud.status:
            disconn_res = self.__quec_cloud.disconnect()
            conn_res = self.__quec_cloud.connect()
            log.debug("Quec cloud reconnect. disconnect: %s connect: %s" % (disconn_res, conn_res))
        return self.__quec_cloud.status

    def __pm_init(self):
        """Enable power management(低功耗)
        """
        pm.autosleep(1)
        if not self.__lpm_fd:
            self.__lpm_fd = pm.create_wakelock(self.__pm_lock_name, len(self.__pm_lock_name))

    def add_module(self, module):
        if isinstance(module, Settings):
            self.__settings = module
            return True
        elif isinstance(module, GPS):
            self.__gps = module
            return True
        elif isinstance(module, XinghengSifProtocol) or isinstance(module, XinghengRs485Protocol):
            self.__bms_protocol = module
            return True
        elif isinstance(module, QuecObjectModel):
            self.__quec_objmodel = module
            return True
        elif isinstance(module, QuecThing):
            self.__quec_cloud = module
            return True
        elif isinstance(module, QuecOTA):
            self.__quec_ota = module
            return True
        elif isinstance(module, NMEAParse):
            self.__nmea_parse = module
            return True

        return False

    def __report_alarm_data(self):
        """Check the battery fault state, send data to the cloud
        """
        if self.__bms_protocol.get_battery_fault_state() and self.__last_fault_state == False:
            report_data = self.__init_alarm_data()
            self.__data_report(report_data)
            self.__report_cell_volt_data()
        elif self.__bms_protocol.get_battery_fault_state() == False and self.__last_fault_state == True:
                report_data = self.__init_alarm_data()
                self.__data_report(report_data)
                self.__report_cell_volt_data()
        self.__last_fault_state = self.__bms_protocol.get_battery_fault_state()

    def running(self):
        """BMS box main routine
        """
        self.__net_connect()
        _settings = self.__settings.get()
        # QuecIot connect and save device secret.
        if _settings["quec_cloud_cfg"]["dk"] and not _settings["quec_cloud_cfg"]["ds"] and self.__quec_cloud.device_secret:
            self.__set_config({"ds": self.__quec_cloud.device_secret})
        self.__report_period_time = _settings["user_cfg"]["reportTimes"]
        # Open gps
        self.__gps.open()
        self.__pm_init()
        while True:
            if self.__enter_low_power == True:
                # Disconnect QuecIot
                self.__quec_cloud.disconnect()
                self.__gps.close()
                if isinstance(self.__bms_protocol, XinghengSifProtocol):
                    # Stop acctimer,reduce power consumption
                    sif.acctimer_stop()
                # No data received, the system enters low power mode
                log.debug("enter low power")
                if self.__bms_protocol.received_data():
                    self.__quec_cloud.connect()
                    self.__gps.open()
                    log.debug("exit low power")
                    self.__enter_low_power = False
            else: 
                if utime.time() - self.__data_report_start_timestamp >= self.__report_period_time:
                    report_data = self.__init_report_data()
                    self.__data_report(report_data)
                    self.__report_cell_volt_data()
                    log.debug("report data to quecthing")
                    # Device version report and OTA plain search
                    if self.__cloud_conn_status():
                        _res = self.__quec_cloud.device_report()
                        log.debug("Quec device report %s" % "success" if _res else "falied")
                        _res = self.__quec_cloud.ota_search()
                        log.debug("Quec ota search %s" % "success" if _res else "falied")
                    self.__data_report_start_timestamp = utime.time()
                # Report battery alarm infomation
                self.__report_alarm_data()
                if utime.time() - self.__bms_protocol.get_data_fresh_timestamp() >= 30:
                    self.__enter_low_power = True
            utime.sleep_ms(50)

    def execute(self, args):
        if args[0] == 5 and args[1] == 10200:
            log.debug("transparent data: %s" % args[1])
        elif args[0] == 5 and args[1] == 10210:
            self.__set_objmodel(args[2])
        elif args[0] == 5 and args[1] == 10220:
            self.__query_objmodel(args[2])
        elif args[0] == 7:
            log.debug("QuecIot OTA errcode[%s] data[%s]" % tuple(args[1:]))
            self.__ota(*args[1:])
        else:
            log.error("Mode %s is not support. data: %s" % (str(args[0]), str(args[1])))


def main():
    log.info("PROJECT_NAME: %s, PROJECT_VERSION: %s" % (PROJECT_NAME, PROJECT_VERSION))
    log.info("DEVICE_FIRMWARE_NAME: %s, DEVICE_FIRMWARE_VERSION: %s" % (DEVICE_FIRMWARE_NAME, DEVICE_FIRMWARE_VERSION))

    class _bms_protocol:
        sif = 0x0
        rs485 = 0x1

    settings = Settings()
    _settings = settings.get()

    quec_ota = QuecOTA()
    quec_objmodel = QuecObjectModel()
    quec_cloud = QuecThing(**_settings["quec_cloud_cfg"])

    nema_parse = NMEAParse()
    gps = GPS(**_settings["loc_cfg"]["gps_cfg"])
    if _settings["user_cfg"]["bms_protocol"] == _bms_protocol.sif:
        bms_protocol = XinghengSifProtocol(gpio = _settings["user_cfg"]["sif_gpio_pin"])
    elif _settings["user_cfg"]["bms_protocol"] == _bms_protocol.rs485:
        bms_protocol = XinghengRs485Protocol(
            _settings["user_cfg"]["rs485_config"]["UARTn"],
            _settings["user_cfg"]["rs485_config"]["buadrate"],
            _settings["user_cfg"]["rs485_config"]["databits"],
            _settings["user_cfg"]["rs485_config"]["parity"],
            _settings["user_cfg"]["rs485_config"]["stopbits"],
            _settings["user_cfg"]["rs485_config"]["flowctl"],
            _settings["user_cfg"]["rs485_config"]["rs485_pin"],
            en_req=True
            )

    bms_box = BmsBox()
    bms_box.add_module(settings)
    bms_box.add_module(quec_objmodel)
    bms_box.add_module(quec_cloud)
    bms_box.add_module(quec_ota)
    bms_box.add_module(nema_parse)
    bms_box.add_module(gps)
    bms_box.add_module(bms_protocol)

    quec_cloud.set_callback(bms_box.execute)
    quec_cloud.connect()
    _thread.start_new_thread(bms_box.running, ())


if __name__ == "__main__":
    main()
