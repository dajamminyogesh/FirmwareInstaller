'''
Created on 2017年8月15日

@author: CreatBot-SW
'''
import io


# ===============================================================================
# Module to read intel hex files into binary data blobs.
# IntelHex files are commonly used to distribute firmware
# See: http://en.wikipedia.org/wiki/Intel_HEX
# ===============================================================================


def readHex(filename):
    """
    Read an verify an intel hex file. Return the data as an list of bytes.
    """
    data = []
    extraAddr = 0
    f = io.open(filename, "r")
    for line in f:
        line = line.strip()
        if line[0] != ':':
            raise formatError("Hex file must start with ':' @ " + line)
        recLen = int(line[1:3], 16)
        addr = int(line[3:7], 16) + extraAddr
        recType = int(line[7:9], 16)
        if len(line) != recLen * 2 + 11:
            raise formatError("Length error in hex file @ " + line)
        checkSum = 0
        for i in range(0, recLen + 5):
            checkSum += int(line[i * 2 + 1:i * 2 + 3], 16)
        checkSum &= 0xFF
        if checkSum != 0:
            raise formatError("Checksum error in hex file @ " + line)

        if recType == 0:  # Data record
            while len(data) < addr + recLen:
                data.append(0)
            for i in range(0, recLen):
                data[addr + i] = int(line[i * 2 + 9:i * 2 + 11], 16)
        elif recType == 1:  # End Of File record
            pass
        elif recType == 2:  # Extended Segment Address Record
            extraAddr = int(line[9:13], 16) * 16
        elif recType == 3:  # Start Segment Address Record
            raise formatError("Dont support record type 03")
        elif recType == 4:  # Extended Linear Address Record
            extraAddr = int(line[9:13], 16) << 16
        elif recType == 5:  # Start Linear Address Record
            raise formatError("Dont support record type 05")
        else:
            print(recType, recLen, addr, checkSum, line)
    f.close()
    return data


class formatError(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)
