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
@file      :xingheng_chg_sif.py
@author    :Elian Wang (elian.wang@quectel.com)
@brief     :
@version   :1.0.0
@date      :2022-10-17 13:36:41
@copyright :Copyright (c) 2022
"""

import sif
import utime
import _thread
import ubinascii
from usr.logging import Logger
from queue import Queue

log = Logger(__name__)

class XinghengSifProtocol():
    """This class is the protocol of xingheng SIF"""
    def __init__(self, gpio):
        """
        Args:
            gpio (int): SIF communiction gpio port
        """
        self.__message_id = 0
        self.__protocol_version = 0
        self.__manufacturer = 0
        self.__bat_type = 0
        self.__battery_cell_material = 0
        self.__rated_volt = 0
        self.__rated_capacity = 0
        self.__remain_capacity = 0
        self.__bat_volt = 0
        self.__electric_current = 0 # 12
        self.__max_temperatiure = 0
        self.__min_temperatiure = 0
        self.__mos_temperatiure = 0

        self.__battery_work_state = 0
        self.__battery_fault = 0
        self.__soc = 0
        self.__allow_charg = False
        self.__illegal_charger_alarm = False
        self.__charger_link_sta = False
        self.__pre_dischg_mos_sta = False
        self.__chg_mos_sta = False
        self.__dischg_mos_sta = False
        self.__dchg_cycle_time = 0
        self.__max_cell_volt = 0
        self.__min_cell_volt = 0
        self.__max_volt_cell_pos = 0
        self.__min_volt_cell_pos = 0
        self.__max_feedback_current = 0
        self.__req_chg_volt = 0
        self.__req_chg_current = 0
        self.__chg_sta = 0
        self.__key = 0
        self.__key_res = 0
        self.__bar = ""
        self.__battery_serial_num = 0
        self.__cell_volt = []
        self.__queue = Queue(maxsize = 1)
        self.__data_fresh_timestamp = utime.time()
        self.__protocol_provider = 1
        self.__device_type = 101 # 101:LTE电池云盒，102：BLE电池云盒
        sif.init(gpio, self.__recv_sif_data_callback)
        
    def __recv_sif_data_callback(self, data):
        if self.__queue.size() == 0:
            self.__queue.put(True)
        log.debug("SIF data: ", ubinascii.hexlify(data, ' '))
        self.__data_fresh_timestamp = utime.time()
        self.__parse_sif_data(data)
        
    def __parse_sif_data(self, data):
        if data != b'':
            try:
                if len(data) == 20 and data[0] == 1: # public message
                    check_sum = sum(data[:-1])
                    if check_sum & 0xff == data[19]:
                        log.debug("SIF public data sum check success")
                        self.__manufacturer = data[2]
                        self.__bat_type = data[3]
                        self.__battery_cell_material = data[4]
                        self.__rated_volt = (data[5] + (data[6] << 8)) / 10
                        self.__rated_capacity = (data[7] + (data[8] << 8)) / 10
                        self.__remain_capacity = data[9] / 2
                        self.__bat_volt = (data[10] + (data[11] << 8)) / 10
                        self.__electric_current = (data[12] + (data[13] << 8)) / 10 - 500
                        self.__max_temperatiure = data[14] - 40
                        self.__min_temperatiure = data[15] - 40
                        self.__mos_temperatiure = data[16] - 40
                        self.__battery_fault = data[17]
                        self.__battery_work_state = data[18]
                elif len(data) == (data[2]+4) and data[0] == 0x3A:
                    check_sum = sum(data[:-1])
                    if check_sum & 0xff == data[-1]:
                        log.debug("SIF private data1 sum check success")
                        self.__soc = data[3] / 2
                        self.__bat_volt = (data[4] + (data[5] << 8)) / 10
                        self.__electric_current = (data[6] + (data[7] << 8)) / 10 - 500
                        self.__max_temperatiure = data[8] - 40
                        self.__min_temperatiure = data[9] - 40
                        self.__mos_temperatiure = data[10] - 40
                        self.__battery_fault = data[11]
                        self.__battery_work_state = data[12]
                        self.__allow_charg = True if data[13] & 0x01 else False
                        self.__illegal_charger_alarm = True if data[13] & 0x02 else False
                        self.__charger_link_sta = True if data[13] & 0x04 else False
                        self.__pre_dischg_mos_sta = True if data[13] & 0x20 else False
                        self.__chg_mos_sta = True if data[13] & 0x40 else False
                        self.__dischg_mos_sta = True if data[13] & 0x80 else False

                        self.__dchg_cycle_time = data[14] + (data[15] << 8)
                        self.__max_cell_volt = data[16] + (data[17] << 8)
                        self.__min_cell_volt = data[18] + (data[19] << 8)
                        self.__max_volt_cell_pos = data[20]
                        self.__min_volt_cell_pos = data[21]
                        self.__max_feedback_current = data[22]
                        self.__req_chg_volt = data[23] + (data[24] << 8)
                        self.__req_chg_current = data[25]
                        self.__chg_sta = data[26]
                        self.__key = data[27]
                        self.__key_res = data[28:-1]
                elif data[0] == 0x3B and len(data) == (data[2]+4):
                    check_sum = sum(data[:-1])
                    if check_sum & 0xff == data[-1]:
                        log.debug("SIF cell volt sum check success")
                        cell_data_len = data[2]
                        self.__battery_serial_num = cell_data_len / 2
                        i = 0
                        self.__cell_volt = []
                        try:
                            while i < self.__battery_serial_num:
                                self.__cell_volt.append(data[3+2*i]+(data[4+2*i]<<8))
                                i += 1
                        except Exception as e:
                            log.error("SIF cell volt error:", e)

                elif data[0] == 0x3C and len(data) == (data[2]+4):
                    check_sum = sum(data[:-1])
                    if check_sum & 0xff == data[-1]:
                        data_len = data[2]
                        self.__bar = data[3:data_len+3].decode()
            except Exception as e:
                log.error("SIF receive data fault:", e)

    def __init_battery_base_data(self):
        _data = {}
        _data.update({
            "ver": self.__protocol_version,
            "soc": self.__soc,
            "vol": self.__bat_volt,
            "current": self.__electric_current,
            "highTemp": self.__max_temperatiure,
            "lowTemp": self.__min_temperatiure,
            "mosTemp": self.__mos_temperatiure,
            "fault": self.__battery_fault,
            "chargeEnable": self.__allow_charg,
            "chargeWrongful": self.__illegal_charger_alarm,
            "detc": self.__charger_link_sta,
            "dischargeStatus": self.__pre_dischg_mos_sta,
            "dischargeMosStatus": self.__dischg_mos_sta,
            "chargeMosStatus": self.__chg_mos_sta,
            "batteryCycles": self.__dchg_cycle_time,
            "batteryHighVol": self.__max_cell_volt,
            "batteryLowVol": self.__min_cell_volt,
            "highVpos": self.__max_volt_cell_pos,
            "lowVpos": self.__min_volt_cell_pos,
            "feedbackCur": self.__max_feedback_current,
            "seqVol": self.__req_chg_volt,
            "seqCur": self.__req_chg_current,
            "key": self.__key,
            "keyRes": self.__key_res,
            "bar": self.__bar,
           # "mbStatus": sif.__discharge_over_current_protect_2,
            "mbStatus": 1,
            "batteryStatus": self.__battery_work_state,
            "chargeStatus": self.__chg_sta,
        })
        return _data

    def received_data(self):
        if self.__queue.get():
            return True

    def get_data_fresh_timestamp(self):
        return self.__data_fresh_timestamp

    def get_battery_fault_state(self):
        if self.__battery_fault != 0:
            return False
        else:
            return True

    def get_alarm_data(self):
        _data = {}
        if self.__battery_fault == 0x01:
            _data.update({"doc2p" : True})
        elif self.__battery_fault == 0x02:
            _data.update({"doc1p" : True})
        elif self.__battery_fault == 0x03:
            _data.update({"cutp" : True})
        elif self.__battery_fault == 0x04:
            _data.update({"cutp" : True})
        elif self.__battery_fault == 0x05:
            _data.update({"dotp" : True})
        elif self.__battery_fault == 0x06:
            _data.update({"uvp" : True})
        elif self.__battery_fault == 0x07:
            _data.update({"ovp" : True})
        elif self.__battery_fault == 0x08:
            _data.update({"cocp" : True})
        elif self.__battery_fault == 0x09:
            _data.update({"dutp" : True})
        elif self.__battery_fault == 0x0A:
            _data.update({"cmosp" : True})
        elif self.__battery_fault == 0x0B:
            _data.update({"dmosp" : True})
        _data.update(self.__init_battery_base_data())
        return _data

    def get_report_data(self):
        _data = {}
        """
        _data.update({
            "dmospStatus": self.__discharge_mos_fault,
            "cmospStatus": self.__charge_mos_fault,
            "dutpStatus": self.__discharge_under_temp_protect,
            "cocpStatus": self.__charge_over_current_protect,
            "ovpStatus": self.__over_volt_protect,
            "uvpStatus": self.__under_volt_protect,
            "dotpStatus": self.__discharge_over_temp_protect,
            "cotpStatus": self.__charge_over_temp_protect,
            "cutpStatus": self.__charge_under_temp_protect,
            "doc1pStatus": self.__discharge_over_current_protect_1,
            "doc2pStatus": self.__discharge_over_current_protect_2,
        })
        """
        _data.update(self.__init_battery_base_data())

        _data.update({
            # "reportTimes": self.__manufacturer,
            # "srcMessage": self.__manufacturer,
            "merchantCode": self.__manufacturer, # 0x01:星恒，5：爱德邦
            "code": self.__bat_type,
            "material": self.__battery_cell_material,
            "protocolProvider": self.__protocol_provider, # 协议提供商 1：星恒
            "DeviceType": self.__device_type,
        })

        log.debug("report_data: %s" % _data)

        return _data