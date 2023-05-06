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
@file      :xingheng_rs485_protocol.py
@author    :Elian Wang (elian.wang@quectel.com)
@brief     :
@version   :1.0.0
@date      :2022-10-24 15:00:26
@copyright :Copyright (c) 2022
"""

import sif
import usys
import utime
import _thread
import ubinascii
from usr.logging import Logger
from usr.serial import Serial
from machine import UART
from queue import Queue

log = Logger(__name__)

class XinghengRs485Protocol():
    """This class is the protocol of xingheng Rs485"""
    def __init__(self, UARTn, buadrate, databits, parity, stopbits, flowctl, rs485_pin, en_req=False):
        """
        Args:
            UARTn (int): UART port id
        """
        self.__UARTn = UARTn
        self.__buadrate = buadrate
        self.__databits = databits
        self.__parity = parity
        self.__stopbits = stopbits
        self.__flowctl = flowctl
        self.__rs485_pin = rs485_pin
        self.__get_temp_cmd = 0x08
        self.__get_bat_volt_cmd = 0x09
        self.__get_current_cmd = 0x0A
        self.__get_soc_cmd = 0x0d
        self.__get_bat_cycle_cmd = 0x17
        self.__get_cell_volt_cmd1 = 0x24
        self.__get_cell_volt_cmd2 = 0x25
        self.__get_soh_cmd = 0x0C
        self.__get_version_cmd = 0x7F
        self.__get_bat_id_cmd = 0x7E
        self.__bat_temp = 0
        self.__bat_volt = 0
        self.__bat_current = 0
        self.__soc = 0
        self.__bat_cycle_time = 0
        self.__soh = 0
        self.__cell_volt =  [i for i in range(14)]
        self.__sw_version = 0
        self.__hw_version = 0
        self.__bat_id = ""
        self.__battery_serial_num = 0
        self.__battery_fault = 0
        self.__read_data = b''
        self.__queue = Queue(maxsize = 1)
        self.__data_fresh_timestamp = utime.time()
        self.__uart_init()
        _thread.start_new_thread(self.__read_rs485_data, ())
        if en_req:
           _thread.start_new_thread(self.__request_bat_info, ())
        
    def __uart_init(self):
        self.__uart_obj = Serial(
            self.__UARTn, 
            self.__buadrate, 
            self.__databits, 
            self.__parity,
            self.__stopbits,
            self.__flowctl,
            self.__rs485_pin
        )

    def __checksum_value_check_legal(self, data):
        if len(data) < 9:
            return False
        checksum_value = (data[-3] << 8) + data[-4]
        if sum(data[1:-4]) == checksum_value:
            return True
        else:
            return False

    def __calculate_checksum_value(self, data_str):
        _data = ubinascii.unhexlify(data_str)
        data = _data + sum(_data[1:]).to_bytes(2, "little")
        return data

    def __send_rs485_cmd(self, cmd):
        send_data = "3A16" + "{:02X}".format(cmd) + "0100"
        data = self.__calculate_checksum_value(send_data) + ubinascii.unhexlify("0D0A")
        self.__uart_obj.write(data)
        
    def __parse(self):
        while True:
            if len(self.__read_data) < 9:
                break
            if self.__read_data[0:2] != ubinascii.unhexlify("3A16"):
                self.__read_data = b''
                break

            frame_byte_len = self.__read_data[3] + 8
            if len(self.__read_data) < frame_byte_len:
                break
            parse_data = self.__read_data[0:frame_byte_len]
            if self.__checksum_value_check_legal(parse_data) \
                and parse_data[-2:] == ubinascii.unhexlify("0D0A"):
                if self.__queue.size() == 0:
                    self.__queue.put(True)
                self.__data_fresh_timestamp = utime.time()

                if parse_data[2] == self.__get_temp_cmd:
                    if parse_data[3] >= 2:
                        self.__bat_temp = ((parse_data[5]<<8)+parse_data[4] - 2731)/10
                        print("bat_temp", self.__bat_temp)
                elif parse_data[2] == self.__get_bat_volt_cmd:
                    if parse_data[3] >= 2:
                        self.__bat_volt = ((parse_data[5]<<8)+parse_data[4]) / 1000
                        print("__bat_volt", self.__bat_volt)
                elif parse_data[2] == self.__get_current_cmd:
                    if parse_data[3] >= 4:
                        self.__bat_current = ((parse_data[7]<<24)+(parse_data[6]<<16)+(parse_data[5]<<8)+parse_data[4]) / 1000
                        print("__bat_current", self.__ba__bat_currentt_volt)
                elif parse_data[2] == self.__get_soc_cmd:
                    self.__soc = parse_data[5]
                    print("__soc", self.__soc)
                elif parse_data[2] == self.__get_bat_cycle_cmd:
                    if parse_data[3] >= 2:
                        self.__bat_cycle_time = (parse_data[5]<<8)+parse_data[4]
                        print("__bat_cycle_time", self.__bat_cycle_time)
                elif parse_data[2] == self.__get_cell_volt_cmd1:
                    if parse_data[3] >= 14:
                        self.__cell_volt[0] = (parse_data[5]<<8)+parse_data[4]
                        self.__cell_volt[1] = (parse_data[7]<<8)+parse_data[6]
                        self.__cell_volt[2] = (parse_data[9]<<8)+parse_data[8]
                        self.__cell_volt[3] = (parse_data[11]<<8)+parse_data[10]
                        self.__cell_volt[4] = (parse_data[13]<<8)+parse_data[12]
                        self.__cell_volt[5] = (parse_data[15]<<8)+parse_data[14]
                        self.__cell_volt[6] = (parse_data[17]<<8)+parse_data[16]
                        print("__cell_volt[0]", self.__cell_volt[0])
                elif parse_data[2] == self.__get_cell_volt_cmd2:
                    data_len = parse_data[3]
                    self.__battery_serial_num = 7 + data_len/2
                    print("battery_serial_num:", self.__battery_serial_num)
                    if data_len >= 2:
                        i = 0
                        while i < data_len/2:
                            self.__cell_volt[7+i] = (parse_data[5+2*i]<<8) + parse_data[4+2*i]
                            i += 1
                    print("__cell_volt[9]", self.__cell_volt[9])
                elif parse_data[2] == self.__get_soh_cmd:
                    if parse_data[3] >= 1:
                        self.__soh = parse_data[4]
                        print("__soh", self.__soh)
                elif parse_data[2] == self.__get_version_cmd:
                    data_len = parse_data[3]
                    if data_len >= 2:
                        self.__sw_version = parse_data[4]
                        self.__hw_version = parse_data[5]
                        print("__sw_version", self.__sw_version)
                elif parse_data[2] == self.__get_bat_id_cmd:
                    data_len = parse_data[3]
                    if data_len >= 2:
                        self.__bat_id = parse_data[4:5+data_len].decode()
                        print("__bat_id", self.__bat_id)
                self.__read_data = self.__read_data[frame_byte_len:]
            else:
                self.__read_data = b''
                break

    def __read_rs485_data(self):
        while True:
            data = self.__uart_obj.read(1024, -1).encode()
            log.debug("UART data: ", ubinascii.hexlify(data, ' '))
            #print("uart data len:", len(read_data))
            self.__read_data += data
            try:
                if len(self.__read_data) > 0:
                    self.__parse()
            except Exception as e:
                log.error("Read RS485 data error:", e)
                usys.print_exception(e)
                return False
        
    def __request_bat_info(self):
        while True:
            self.__send_rs485_cmd(self.__get_temp_cmd)
            utime.sleep(0.5)

            self.__send_rs485_cmd(self.__get_bat_volt_cmd)
            utime.sleep(0.5)

            self.__send_rs485_cmd(self.__get_current_cmd)
            utime.sleep(0.5)

            self.__send_rs485_cmd(self.__get_soc_cmd)
            utime.sleep(0.5)

            self.__send_rs485_cmd(self.__get_bat_cycle_cmd)
            utime.sleep(0.5)

            self.__send_rs485_cmd(self.__get_cell_volt_cmd1)
            utime.sleep(0.5)

            self.__send_rs485_cmd(self.__get_cell_volt_cmd2)
            utime.sleep(0.5)

            self.__send_rs485_cmd(self.__get_soh_cmd)
            utime.sleep(0.5)

            self.__send_rs485_cmd(self.__get_version_cmd)
            utime.sleep(0.5)

            self.__send_rs485_cmd(self.__get_bat_id_cmd)
            utime.sleep(0.5)

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
        return _data

    def get_report_data(self):
        _data = {}
        
        _data.update({
            "ver": self.__sw_version,
            "soc": self.__soc,
            "vol": self.__bat_volt,
            "current": self.__bat_current,
            "highTemp": self.__bat_temp,
            "lowTemp": self.__bat_temp,
            "mosTemp": self.__bat_temp,
            "batteryCycles": self.__bat_cycle_time,
            "bar": self.__bat_id,
        })

        _data.update({
            "merchantCode": 0x01, # 0x01:星恒，5：爱德邦
            "protocolProvider": 0x01, # 协议提供商 1：星恒
            "DeviceType": 0x65,
        })

        log.debug("report_data: %s" % _data)

        return _data


