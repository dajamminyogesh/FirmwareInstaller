#!/usr/bin/env python
# This file is part of the OpenMV project.
# Copyright (c) 2013/2014 Ibrahim Abdelkader <i.abdalkader@gmail.com>
# This work is licensed under the MIT license, see the file LICENSE for
# details.

"""This module implements enough functionality to program the STM32F4xx over
DFU, without requiring dfu-util.

See app note AN3156 for a description of the DFU protocol.
See document UM0391 for a dscription of the DFuse file.
"""

from __future__ import print_function

import argparse
import collections
import inspect
import re
import struct
import sys
import time
import zlib

import usb.core
import usb.util

# USB request __TIMEOUT
__TIMEOUT = 4000

# DFU commands
__DFU_DETACH = 0
__DFU_DNLOAD = 1
__DFU_UPLOAD = 2
__DFU_GETSTATUS = 3
__DFU_CLRSTATUS = 4
__DFU_GETSTATE = 5
__DFU_ABORT = 6

# DFU status
__DFU_STATE_APP_IDLE = 0x00
__DFU_STATE_APP_DETACH = 0x01
__DFU_STATE_DFU_IDLE = 0x02
__DFU_STATE_DFU_DOWNLOAD_SYNC = 0x03
__DFU_STATE_DFU_DOWNLOAD_BUSY = 0x04
__DFU_STATE_DFU_DOWNLOAD_IDLE = 0x05
__DFU_STATE_DFU_MANIFEST_SYNC = 0x06
__DFU_STATE_DFU_MANIFEST = 0x07
__DFU_STATE_DFU_MANIFEST_WAIT_RESET = 0x08
__DFU_STATE_DFU_UPLOAD_IDLE = 0x09
__DFU_STATE_DFU_ERROR = 0x0A

_DFU_DESCRIPTOR_TYPE = 0x21

__DFU_STATUS_STR = {
    __DFU_STATE_APP_IDLE: "STATE_APP_IDLE",
    __DFU_STATE_APP_DETACH: "STATE_APP_DETACH",
    __DFU_STATE_DFU_IDLE: "STATE_DFU_IDLE",
    __DFU_STATE_DFU_DOWNLOAD_SYNC: "STATE_DFU_DOWNLOAD_SYNC",
    __DFU_STATE_DFU_DOWNLOAD_BUSY: "STATE_DFU_DOWNLOAD_BUSY",
    __DFU_STATE_DFU_DOWNLOAD_IDLE: "STATE_DFU_DOWNLOAD_IDLE",
    __DFU_STATE_DFU_MANIFEST_SYNC: "STATE_DFU_MANIFEST_SYNC",
    __DFU_STATE_DFU_MANIFEST: "STATE_DFU_MANIFEST",
    __DFU_STATE_DFU_MANIFEST_WAIT_RESET: "STATE_DFU_MANIFEST_WAIT_RESET",
    __DFU_STATE_DFU_UPLOAD_IDLE: "STATE_DFU_UPLOAD_IDLE",
    __DFU_STATE_DFU_ERROR: "STATE_DFU_ERROR",
}

# USB device handle
__dev = None

# Configuration descriptor of the device
__cfg_descr = None

__verbose = None

# USB DFU interface
__DFU_INTERFACE = 0

# Python 3 deprecated getargspec in favour of getfullargspec, but
# Python 2 doesn't have the latter, so detect which one to use
getargspec = getattr(inspect, "getfullargspec", inspect.getargspec)

if "length" in getargspec(usb.util.get_string).args:
    # PyUSB 1.0.0.b1 has the length argument
    def get_string(dev, index):
        return usb.util.get_string(dev, 255, index)


else:
    # PyUSB 1.0.0.b2 dropped the length argument
    def get_string(dev, index):
        return usb.util.get_string(dev, index)


def find_dfu_cfg_descr(descr):
    if len(descr) == 9 and descr[0] == 9 and descr[1] == _DFU_DESCRIPTOR_TYPE:
        nt = collections.namedtuple(
            "CfgDescr",
            [
                "bLength",
                "bDescriptorType",
                "bmAttributes",
                "wDetachTimeOut",
                "wTransferSize",
                "bcdDFUVersion",
            ],
        )
        return nt(*struct.unpack("<BBBHHH", bytearray(descr)))
    return None


def init(**kwargs):
    """Initializes the found DFU device so that we can program it."""
    global __dev, __cfg_descr
    devices = get_dfu_devices(**kwargs)
    if not devices:
        raise ValueError("No DFU device found")
    if len(devices) > 1:
        raise ValueError("Multiple DFU devices found")
    __dev = devices[0]
    __dev.set_configuration()

    # Claim DFU interface
    usb.util.claim_interface(__dev, __DFU_INTERFACE)

    # Find the DFU configuration descriptor, either in the device or interfaces
    __cfg_descr = None
    for cfg in __dev.configurations():
        __cfg_descr = find_dfu_cfg_descr(cfg.extra_descriptors)
        if __cfg_descr:
            break
        for itf in cfg.interfaces():
            __cfg_descr = find_dfu_cfg_descr(itf.extra_descriptors)
            if __cfg_descr:
                break

    # Get device into idle state
    for attempt in range(4):
        status = get_status()
        if status == __DFU_STATE_DFU_IDLE:
            break
        elif status == __DFU_STATE_DFU_DOWNLOAD_IDLE or status == __DFU_STATE_DFU_UPLOAD_IDLE:
            abort_request()
        else:
            clr_status()


def abort_request():
    """Sends an abort request."""
    __dev.ctrl_transfer(0x21, __DFU_ABORT, 0, __DFU_INTERFACE, None, __TIMEOUT)


def clr_status():
    """Clears any error status (perhaps left over from a previous session)."""
    __dev.ctrl_transfer(0x21, __DFU_CLRSTATUS, 0, __DFU_INTERFACE, None, __TIMEOUT)


def get_status():
    """Get the status of the last operation."""
    stat = __dev.ctrl_transfer(0xA1, __DFU_GETSTATUS, 0, __DFU_INTERFACE, 6, 20000)

    # firmware can provide an optional string for any error
    if stat[5]:
        message = get_string(__dev, stat[5])
        if message:
            print(message)

    return stat[4]


def check_status(stage, expected):
    status = get_status()
    if status != expected:
        raise SystemExit("DFU: %s failed (%s)" % (stage, __DFU_STATUS_STR.get(status, status)))


def mass_erase():
    """Performs a MASS erase (i.e. erases the entire device)."""
    # Send DNLOAD with first byte=0x41
    __dev.ctrl_transfer(0x21, __DFU_DNLOAD, 0, __DFU_INTERFACE, "\x41", __TIMEOUT)

    # Execute last command
    check_status("erase", __DFU_STATE_DFU_DOWNLOAD_BUSY)

    # Check command state
    check_status("erase", __DFU_STATE_DFU_DOWNLOAD_IDLE)


def page_erase(addr):
    """Erases a single page."""
    if __verbose:
        print("Erasing page: 0x%x..." % (addr))

    # Send DNLOAD with first byte=0x41 and page address
    buf = struct.pack("<BI", 0x41, addr)
    __dev.ctrl_transfer(0x21, __DFU_DNLOAD, 0, __DFU_INTERFACE, buf, __TIMEOUT)

    # Execute last command
    check_status("erase", __DFU_STATE_DFU_DOWNLOAD_BUSY)

    # Check command state
    check_status("erase", __DFU_STATE_DFU_DOWNLOAD_IDLE)


def set_address(addr):
    """Sets the address for the next operation."""
    # Send DNLOAD with first byte=0x21 and page address
    buf = struct.pack("<BI", 0x21, addr)
    __dev.ctrl_transfer(0x21, __DFU_DNLOAD, 0, __DFU_INTERFACE, buf, __TIMEOUT)

    # Execute last command
    check_status("set address", __DFU_STATE_DFU_DOWNLOAD_BUSY)

    # Check command state
    check_status("set address", __DFU_STATE_DFU_DOWNLOAD_IDLE)


def write_memory(addr, buf, progress=None, progress_addr=0, progress_size=0):
    """Writes a buffer into memory. This routine assumes that memory has
    already been erased.
    """

    xfer_count = 0
    xfer_bytes = 0
    xfer_total = len(buf)
    xfer_base = addr

    while xfer_bytes < xfer_total:
        if __verbose and xfer_count % 512 == 0:
            print(
                "Addr 0x%x %dKBs/%dKBs..."
                % (xfer_base + xfer_bytes, xfer_bytes // 1024, xfer_total // 1024)
            )
        if progress and xfer_count % 2 == 0:
            progress(progress_addr, xfer_base + xfer_bytes - progress_addr, progress_size)

        # Set mem write address
        set_address(xfer_base + xfer_bytes)

        # Send DNLOAD with fw data
        chunk = min(__cfg_descr.wTransferSize, xfer_total - xfer_bytes)
        __dev.ctrl_transfer(
            0x21, __DFU_DNLOAD, 2, __DFU_INTERFACE, buf[xfer_bytes: xfer_bytes + chunk], __TIMEOUT
        )

        # Execute last command
        check_status("write memory", __DFU_STATE_DFU_DOWNLOAD_BUSY)

        # Check command state
        check_status("write memory", __DFU_STATE_DFU_DOWNLOAD_IDLE)

        xfer_count += 1
        xfer_bytes += chunk


def write_page(buf, xfer_offset):
    """Writes a single page. This routine assumes that memory has already
    been erased.
    """

    xfer_base = 0x08000000

    # Set mem write address
    set_address(xfer_base + xfer_offset)

    # Send DNLOAD with fw data
    __dev.ctrl_transfer(0x21, __DFU_DNLOAD, 2, __DFU_INTERFACE, buf, __TIMEOUT)

    # Execute last command
    check_status("write memory", __DFU_STATE_DFU_DOWNLOAD_BUSY)

    # Check command state
    check_status("write memory", __DFU_STATE_DFU_DOWNLOAD_IDLE)

    if __verbose:
        print("Write: 0x%x " % (xfer_base + xfer_offset))


def exit_dfu():
    """Exit DFU mode, and start running the program."""
    # Set jump address
    set_address(0x08000000)

    # Send DNLOAD with 0 length to exit DFU
    __dev.ctrl_transfer(0x21, __DFU_DNLOAD, 0, __DFU_INTERFACE, None, __TIMEOUT)

    try:
        # Execute last command
        if get_status() != __DFU_STATE_DFU_MANIFEST:
            print("Failed to reset device")

        # Release device
        usb.util.dispose_resources(__dev)
    except:
        pass


def named(values, names):
    """Creates a dict with `names` as fields, and `values` as values."""
    return dict(zip(names.split(), values))


def consume(fmt, data, names):
    """Parses the struct defined by `fmt` from `data`, stores the parsed fields
    into a named tuple using `names`. Returns the named tuple, and the data
    with the struct stripped off."""

    size = struct.calcsize(fmt)
    return named(struct.unpack(fmt, data[:size]), names), data[size:]


def cstring(string):
    """Extracts a null-terminated string from a byte array."""

    return string.decode("utf-8", "ignore").split("\0", 1)[0]


def compute_crc(data):
    """Computes the CRC32 value for the data passed in."""
    return 0xFFFFFFFF & -zlib.crc32(data) - 1


def read_dfu_file(filename):
    """Reads a DFU file, and parses the individual elements from the file.
    Returns an array of elements. Each element is a dictionary with the
    following keys:
        num     - The element index.
        address - The address that the element data should be written to.
        size    - The size of the element data.
        data    - The element data.
    If an error occurs while parsing the file, then None is returned.
    """

    print("File: {}".format(filename))
    with open(filename, "rb") as fin:
        data = fin.read()
    crc = compute_crc(data[:-4])
    elements = []

    # Decode the DFU Prefix
    #
    # <5sBIB
    #   <   little endian           Endianness
    #   5s  char[5]     signature   "DfuSe"
    #   B   uint8_t     version     1
    #   I   uint32_t    size        Size of the DFU file (without suffix)
    #   B   uint8_t     targets     Number of targets
    dfu_prefix, data = consume("<5sBIB", data, "signature version size targets")
    print(
        "    %(signature)s v%(version)d, image size: %(size)d, "
        "targets: %(targets)d" % dfu_prefix
    )
    for target_idx in range(dfu_prefix["targets"]):
        # Decode the Image Prefix
        #
        # <6sBI255s2I
        #   <       little endian           Endianness
        #   6s      char[6]     signature   "Target"
        #   B       uint8_t     altsetting
        #   I       uint32_t    named       Bool indicating if a name was used
        #   255s    char[255]   name        Name of the target
        #   I       uint32_t    size        Size of image (without prefix)
        #   I       uint32_t    elements    Number of elements in the image
        img_prefix, data = consume(
            "<6sBI255s2I", data, "signature altsetting named name " "size elements"
        )
        img_prefix["num"] = target_idx
        if img_prefix["named"]:
            img_prefix["name"] = cstring(img_prefix["name"])
        else:
            img_prefix["name"] = ""
        print(
            "    %(signature)s %(num)d, alt setting: %(altsetting)s, "
            'name: "%(name)s", size: %(size)d, elements: %(elements)d' % img_prefix
        )

        target_size = img_prefix["size"]
        target_data = data[:target_size]
        data = data[target_size:]
        for elem_idx in range(img_prefix["elements"]):
            # Decode target prefix
            #
            # <2I
            #   <   little endian           Endianness
            #   I   uint32_t    element     Address
            #   I   uint32_t    element     Size
            elem_prefix, target_data = consume("<2I", target_data, "addr size")
            elem_prefix["num"] = elem_idx
            print("      %(num)d, address: 0x%(addr)08x, size: %(size)d" % elem_prefix)
            elem_size = elem_prefix["size"]
            elem_data = target_data[:elem_size]
            target_data = target_data[elem_size:]
            elem_prefix["data"] = elem_data
            elements.append(elem_prefix)

        if len(target_data):
            print("target %d PARSE ERROR" % target_idx)

    # Decode DFU Suffix
    #
    # <4H3sBI
    #   <   little endian           Endianness
    #   H   uint16_t    device      Firmware version
    #   H   uint16_t    product
    #   H   uint16_t    vendor
    #   H   uint16_t    dfu         0x11a   (DFU file format version)
    #   3s  char[3]     ufd         "UFD"
    #   B   uint8_t     len         16
    #   I   uint32_t    crc32       Checksum
    dfu_suffix = named(
        struct.unpack("<4H3sBI", data[:16]), "device product vendor dfu ufd len crc"
    )
    print(
        "    usb: %(vendor)04x:%(product)04x, device: 0x%(device)04x, "
        "dfu: 0x%(dfu)04x, %(ufd)s, %(len)d, 0x%(crc)08x" % dfu_suffix
    )
    if crc != dfu_suffix["crc"]:
        print("CRC ERROR: computed crc32 is 0x%08x" % crc)
        return
    data = data[16:]
    if data:
        print("PARSE ERROR")
        return

    return elements


class FilterDFU(object):
    """Class for filtering USB devices to identify devices which are in DFU
    mode.
    """

    def __call__(self, device):
        for cfg in device:
            for intf in cfg:
                return intf.bInterfaceClass == 0xFE and intf.bInterfaceSubClass == 1


def get_dfu_devices(*args, **kwargs):
    """Returns a list of USB devices which are currently in DFU mode.
    Additional filters (like idProduct and idVendor) can be passed in
    to refine the search.
    """

    # Convert to list for compatibility with newer PyUSB
    return list(usb.core.find(*args, find_all=True, custom_match=FilterDFU(), **kwargs))


def get_memory_layout(device):
    """Returns an array which identifies the memory layout. Each entry
    of the array will contain a dictionary with the following keys:
        addr        - Address of this memory segment.
        last_addr   - Last address contained within the memory segment.
        size        - Size of the segment, in bytes.
        num_pages   - Number of pages in the segment.
        page_size   - Size of each page, in bytes.
    """

    cfg = device[0]
    intf = cfg[(0, 0)]
    mem_layout_str = get_string(device, intf.iInterface)
    mem_layout = mem_layout_str.split("/")
    result = []
    for mem_layout_index in range(1, len(mem_layout), 2):
        addr = int(mem_layout[mem_layout_index], 0)
        segments = mem_layout[mem_layout_index + 1].split(",")
        seg_re = re.compile(r"(\d+)\*(\d+)(.)(.)")
        for segment in segments:
            seg_match = seg_re.match(segment)
            num_pages = int(seg_match.groups()[0], 10)
            page_size = int(seg_match.groups()[1], 10)
            multiplier = seg_match.groups()[2]
            if multiplier == "K":
                page_size *= 1024
            if multiplier == "M":
                page_size *= 1024 * 1024
            size = num_pages * page_size
            last_addr = addr + size - 1
            result.append(
                named(
                    (addr, last_addr, size, num_pages, page_size),
                    "addr last_addr size num_pages page_size",
                )
            )
            addr += size
    return result


def list_dfu_devices(*args, **kwargs):
    """Prints a lits of devices detected in DFU mode."""
    devices = get_dfu_devices(*args, **kwargs)
    if not devices:
        raise SystemExit("No DFU capable devices found")
    for device in devices:
        print(
            "Bus {} Device {:03d}: ID {:04x}:{:04x}".format(
                device.bus, device.address, device.idVendor, device.idProduct
            )
        )
        layout = get_memory_layout(device)
        print("Memory Layout")
        for entry in layout:
            print(
                "    0x{:x} {:2d} pages of {:3d}K bytes".format(
                    entry["addr"], entry["num_pages"], entry["page_size"] // 1024
                )
            )


def write_elements(elements, mass_erase_used, progress=None):
    """Writes the indicated elements into the target memory,
    erasing as needed.
    """
    mem_layout = get_memory_layout(__dev)
    for elem in elements:
        addr = elem["addr"]
        size = elem["size"]  # 固件总长度
        data = elem["data"]
        elem_size = size
        elem_addr = addr
        if progress and elem_size:
            progress(elem_addr, 0, elem_size)
        while size > 0:
            write_size = size
            if not mass_erase_used:
                for segment in mem_layout:
                    if addr >= segment["addr"] and addr <= segment["last_addr"]:
                        # We found the page containing the address we want to
                        # write, erase it
                        page_size = segment["page_size"]
                        page_addr = addr & ~(page_size - 1)
                        if addr + write_size > page_addr + page_size:
                            write_size = page_addr + page_size - addr
                        page_erase(page_addr)
                        break
            print("addr===", addr, "\nwrite_size===", write_size, "\n", progress, "elem_addr===", elem_addr,
                  "elem_size===", elem_size)
            write_memory(addr, data[:write_size], progress, elem_addr, elem_size)
            data = data[write_size:]
            addr += write_size
            size -= write_size
            if progress:
                progress(elem_addr, addr - elem_addr, elem_size)


def cli_progress(addr, offset, size):
    """Prints a progress report suitable for use on the command line."""
    width = 25
    done = offset * width // size
    print(
        "\r0x{:08x} {:7d} [{}{}] {:3d}% ".format(
            addr, size, "=" * done, " " * (width - done), offset * 100 // size
        ),
        end="",
    )
    try:
        sys.stdout.flush()
    except OSError:
        pass  # Ignore Windows CLI "WinError 87" on Python 3.6
    if offset == size:
        print("")


def main():
    """Test program for verifying this files functionality."""
    global __verbose
    # Parse CMD args
    parser = argparse.ArgumentParser(description="DFU Python Util")
    parser.add_argument(
        "-l", "--list", help="list available DFU devices", action="store_true", default=False
    )
    # parser.add_argument("--vid", help="USB Vendor ID", type=lambda x: int(x, 0), default=None)
    # parser.add_argument("--pid", help="USB Product ID", type=lambda x: int(x, 0), default=None)
    parser.add_argument(
        "-m", "--mass-erase", help="mass erase device", action="store_true", default=False
    )
    # parser.add_argument(
    #     "-u", "--upload", help="read file from DFU device", dest="path", default=False
    # )

    parser.add_argument("--vid", help="USB Vendor ID", type=lambda x: int(x, 0), default=0x0483)
    parser.add_argument("--pid", help="USB Product ID", type=lambda x: int(x, 0), default=0xdf11)
    # parser.add_argument(
    #     "-u", "--upload", help="read file from DFU device", dest="path", default="C:\\Users\\User\\Documents\\stm32-test\\board-STM32F103-Mini\\usbdfu.bin"
    # )
    parser.add_argument(
        "-u", "--upload", help="read file from DFU device", dest="path",
        default="C:\\Users\\User\\Downloads\\stm32loader-master\\max.dfu"
    )

    parser.add_argument("-x", "--exit", help="Exit DFU", action="store_true", default=False)
    parser.add_argument(
        "-v", "--verbose", help="increase output verbosity", action="store_true", default=False
    )
    args = parser.parse_args()

    __verbose = args.verbose

    kwargs = {}
    if args.vid:
        kwargs["idVendor"] = args.vid

    if args.pid:
        kwargs["idProduct"] = args.pid

    if args.list:
        list_dfu_devices(**kwargs)
        return

    init(**kwargs)

    # 测试写入其他类型文件
    # file = "C:\\Users\\User\\Downloads\\stm32loader-master\\pro.bin"
    # data = open(file, 'rb').read()
    #
    # write_page(data, 0)
    # return
    command_run = False
    if args.mass_erase:
        print("Mass erase...")
        mass_erase()
        command_run = True

    if args.path:
        elements = read_dfu_file(args.path)
        if not elements:
            print("No data in dfu file")
            return
        print("Writing memory...")
        write_elements(elements, args.mass_erase, progress=cli_progress)

        print("Exiting DFU...")
        exit_dfu()
        command_run = True

    if args.exit:
        print("Exiting DFU...")
        exit_dfu()
        command_run = True

    if command_run:
        print("Finished")
    else:
        print("No command specified")


# if __name__ == "__main__":
#     main()

from PyQt5.QtCore import QIODevice, QThread, pyqtSignal, QByteArray
from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo
from PyQt5.QtWidgets import QApplication

from avr_isp import ispBase
from avr_isp.errorBase import portError


class STM32Dev(ispBase.IspBase, QSerialPort):
    progressCallback = pyqtSignal(int, int)

    def __init__(self):
        super(STM32Dev, self).__init__()
        self.seq = 1
        self.lastAddr = -1
        self.portInfo = None

    def connect(self, port='COM4', speed=115200):
        print("connect", port)
        self.portInfo = QSerialPortInfo(port)
        print("portInfo", self.portInfo)
        self.setPortName(port)
        # self.setBaudRate(speed)
        # self.setPortName("COM3")
        self.setBaudRate(QSerialPort.Baud115200)
        self.setDataBits(QSerialPort.Data8)
        self.setParity(QSerialPort.NoParity)
        self.setStopBits(QSerialPort.OneStop)
        self.setFlowControl(QSerialPort.NoFlowControl)

        if self.portInfo.isNull():
            raise portError(portError.errorInvalid, port)
        else:
            if self.portInfo.isBusy():
                raise portError(portError.errorBusy, port)
            else:
                if self.open(QIODevice.ReadWrite):
                    # 						self.setBreakEnabled()
                    print("open")
                    # self.entryISP()
                    print("open--end")
                else:
                    raise portError(portError.errorOpen, port)

    def close(self):
        super(STM32Dev, self).close()
        self.portInfo = None

    def serial_DFU(self):
        print("serial_DFU")
        # if not self.open(QIODevice.ReadWrite):
        #     # QtWidgets.QMessageBox.about(self, "提示", "无法打开串口!")
        #     return
        print("1111")
        data = bytes("M9999\r", encoding='utf-8')
        data = QByteArray(data)
        print("2222")
        # self.write(data)
        print(self.write(data))
        print("serial_DFU---end")
        self.close()

    def entryISP(self):
        self.seq = 1
        # Reset the controller
        self.setDataTerminalReady(True)
        QThread.msleep(100)
        self.setDataTerminalReady(False)
        QThread.msleep(200)
        self.clear()
        print("=====")

        recv = self.sendMessage([1])[3:]
        if "".join([chr(c) for c in recv]) != "AVRISP_2":
            raise ispBase.IspError("Unkonwn bootloaders!")

        if self.sendMessage([0x10, 0xc8, 0x64, 0x19, 0x20, 0x00, 0x53, 0x03, 0xac, 0x53, 0x00, 0x00]) != [0x10, 0x00]:
            raise ispBase.IspError("Failed to enter programming mode!")

    def leaveISP(self):
        if self.portInfo is not None:
            if self.sendMessage([0x11]) != [0x11, 0x00]:
                raise ispBase.IspError("Failed to leave programming mode!")

    def isConnected(self):
        return self.isOpen()

    def sendISP(self, data):
        recv = self.sendMessage([0x1D, 4, 4, 0, data[0], data[1], data[2], data[3]])
        return recv[2:6]

    def writeFlash(self, flashData):
        # Set load addr to 0, in case we have more then 64k flash we need to enable the address extension
        pageSize = self.chip['pageSize'] * 2
        flashSize = pageSize * self.chip['pageCount']
        if flashSize > 0xFFFF:
            self.sendMessage([0x06, 0x80, 0x00, 0x00, 0x00])
        else:
            self.sendMessage([0x06, 0x00, 0x00, 0x00, 0x00])

        loadCount = (len(flashData) + pageSize - 1) // pageSize
        for i in range(0, loadCount):
            self.sendMessage([0x13, pageSize >> 8, pageSize & 0xFF, 0xc1, 0x0a, 0x40, 0x4c, 0x20, 0x00, 0x00] + flashData[(i * pageSize):(
                    i * pageSize + pageSize)])
            self.progressCallback.emit(i + 1, loadCount * 2)

    def verifyFlash(self, flashData):
        # Set load addr to 0, in case we have more then 64k flash we need to enable the address extension
        flashSize = self.chip['pageSize'] * 2 * self.chip['pageCount']
        if flashSize > 0xFFFF:
            self.sendMessage([0x06, 0x80, 0x00, 0x00, 0x00])
        else:
            self.sendMessage([0x06, 0x00, 0x00, 0x00, 0x00])

        loadCount = (len(flashData) + 0xFF) // 0x100
        for i in range(0, loadCount):
            recv = self.sendMessage([0x14, 0x01, 0x00, 0x20])[2:0x102]
            self.progressCallback.emit(loadCount + i + 1, loadCount * 2)
            for j in range(0, 0x100):
                if i * 0x100 + j < len(flashData) and flashData[i * 0x100 + j] != recv[j]:
                    raise ispBase.IspError('Verify error at: 0x%x' % (i * 0x100 + j))

    def fastReset(self):
        QThread.msleep(50)
        self.setDataTerminalReady(True)
        self.setDataTerminalReady(False)

    def sendMessage(self, data):
        message = struct.pack(">BBHB", 0x1B, self.seq, len(data), 0x0E)
        for c in data:
            message += struct.pack(">B", c)
        checksum = 0
        for c in message:
            checksum ^= c
        message += struct.pack(">B", checksum)
        try:
            print("----00")
            self.write(message)
            self.flush()
            print("----11")
        except:
            raise ispBase.IspError("Serial send timeout")
        self.seq = (self.seq + 1) & 0xFF
        print("----222")
        # time.sleep(1)
        if self.waitForReadyRead(1000):
            print("----33")
            return self.recvMessage()
        else:
            print("----44")
            raise ispBase.IspError("Serial recv timeout")

    def recvMessage(self):
        state = 'Start'
        checksum = 0
        while True:
            s = self.read(1)
            if len(s) < 1:
                if self.waitForReadyRead(20):
                    continue
                else:
                    raise ispBase.IspError("Serial read timeout")
            b = struct.unpack(">B", s)[0]
            checksum ^= b
            if state == 'Start':
                if b == 0x1B:
                    state = 'GetSeq'
                    checksum = 0x1B
            elif state == 'GetSeq':
                state = 'MsgSize1'
            elif state == 'MsgSize1':
                msgSize = b << 8
                state = 'MsgSize2'
            elif state == 'MsgSize2':
                msgSize |= b
                state = 'Token'
            elif state == 'Token':
                if b != 0x0E:
                    state = 'Start'
                else:
                    state = 'Data'
                    data = []
            elif state == 'Data':
                data.append(b)
                if len(data) == msgSize:
                    state = 'Checksum'
            elif state == 'Checksum':
                if checksum != 0:
                    state = 'Start'
                else:
                    return data


class DFUTool(QThread):
    print("DFUTool(QThread)")
    stateCallback = pyqtSignal([str], [Exception])

    progressCallback = pyqtSignal(int, int)

    def __init__(self, parent, port, speed, filename, callback=None):
        super(DFUTool, self).__init__()
        self.parent = parent
        self.port = port
        self.speed = speed
        self.filename = filename
        self.callback = callback
        self.isWork = False
        self.finished.connect(self.done)
        print("__init__")

        global __verbose
        # Parse CMD args
        parser = argparse.ArgumentParser(description="DFU Python Util")
        parser.add_argument(
            "-l", "--list", help="list available DFU devices", action="store_true", default=False
        )
        # parser.add_argument("--vid", help="USB Vendor ID", type=lambda x: int(x, 0), default=None)
        # parser.add_argument("--pid", help="USB Product ID", type=lambda x: int(x, 0), default=None)
        parser.add_argument(
            "-m", "--mass-erase", help="mass erase device", action="store_true", default=False
        )
        # parser.add_argument(
        #     "-u", "--upload", help="read file from DFU device", dest="path", default=False
        # )

        parser.add_argument("--vid", help="USB Vendor ID", type=lambda x: int(x, 0), default=0x0483)
        parser.add_argument("--pid", help="USB Product ID", type=lambda x: int(x, 0), default=0xdf11)
        # parser.add_argument(
        #     "-u", "--upload", help="read file from DFU device", dest="path", default="C:\\Users\\User\\Documents\\stm32-test\\board-STM32F103-Mini\\usbdfu.bin"
        # )
        parser.add_argument(
            "-u", "--upload", help="read file from DFU device", dest="path",
            default=self.filename
        )

        parser.add_argument("-x", "--exit", help="Exit DFU", action="store_true", default=False)
        parser.add_argument(
            "-v", "--verbose", help="increase output verbosity", action="store_true", default=False
        )
        self.args = parser.parse_args()

        __verbose = self.args.verbose

        kwargs = {}
        if self.args.vid:
            kwargs["idVendor"] = self.args.vid

        if self.args.pid:
            kwargs["idProduct"] = self.args.pid

        def w(state):
            if state is False:
                print("未找到DFU")
                self.stateCallback[Exception].emit(portError(portError.errorOpen, port))
                self.stateCallback[str].emit("Done!")
                self.quit()
                return

            try:
                print("找到DFU")
                self.thread.exit()
                init(**kwargs)
                self.start()
            except Exception as err:
                print("----------------------------======================")
                print(err)
            print(1)

        self.thread = DFUSearch(self, kwargs=kwargs)
        self.thread.searchResults.connect(w)  # 异步完成后执行函数w
        self.thread.start()
        self.isWork = True

    def cl_progress(self, addr, offset, size):
        """Prints a progress report suitable for use on the command line."""
        print("offset", offset, "size", size)
        self.progressCallback.emit(offset, size)

    def disconnect(self, QMetaObject_Connection=None):
        print("QMetaObject_Connection")

    def run(self):
        print("run")
        self.isWork = True
        try:
            print("try")
            with open(self.args.path, "rb") as fin:
                dfu_file = fin.read()

            if dfu_file is None:
                print("file is None")
                return
            elem = {"addr": 134217728, "size": len(dfu_file), "data": dfu_file}

            if self.callback is not None:
                self.progressCallback.connect(self.callback)

            if self.parent is None:
                pass

            else:
                self.stateCallback[str].emit(self.tr("Programming..."))
                write_elements([elem], self.args.mass_erase, progress=self.cl_progress)
            exit_dfu()  # 退出DFU模式
            print("exit_dfu")
        except Exception as err:
            if self.isInterruptionRequested():
                print("int")
            else:
                if self.parent is not None:
                    self.stateCallback[Exception].emit(err)
                    while self.isWork:
                        pass  # 等待父进程处理异常
                else:
                    raise err
            self.isWork = False
        finally:
            self.stateCallback[str].emit("Done!")

    def isReady(self):
        return True

    def done(self):
        print("结束烧录程序")
        if self.parent is not None:
            if self.isWork:
                self.isWork = False
                self.stateCallback[str].emit(self.tr("Done!"))
            else:
                print("Success!")
        else:
            print("Failure!")

    def terminate(self):
        if self.thread.isRunning():
            self.thread.exit()

        self.requestInterruption()
        return super(DFUTool, self).terminate()


class DFUSearch(QThread):
    searchResults = pyqtSignal(bool)  # 信号

    def __init__(self, parent=None, kwargs=None):
        super(DFUSearch, self).__init__()
        self.kwargs = kwargs

    def __del__(self):
        self.wait()

    def run(self):
        # 耗时内容
        print("self.kwargs", self.kwargs)
        devices = get_dfu_devices(**self.kwargs)
        # Waiting 2 seconds before trying again..."
        attempts = 0
        while not devices:
            devices = get_dfu_devices(**self.kwargs)
            attempts += 1
            print("搜索DFU设备", attempts)
            if attempts > 20:
                self.searchResults.emit(False)
                self.quit()
                return
            time.sleep(1)

        self.searchResults.emit(True)

    def terminate(self):
        self.requestInterruption()
        return super(DFUSearch, self).terminate()


if __name__ == '__main__':
    # 	main()
    app = QApplication(sys.argv)
    task = DFUTool(None, None)
    # 	task = stk500v2Thread(None, "COM4", 115200, "D:/OneDrive/Desktop/test.hex")
    try:
        task.start()
    except Exception as e:
        print(e)

    sys.exit(app.exec())
