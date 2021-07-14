'''
Created on 2017年8月15日

@author: CreatBot-SW
'''
#===============================================================================
# STK500v2 protocol implementation for programming AVR chips.
# The STK500v2 protocol is used by the ArduinoMega2560 and a few other Arduino platforms to load firmware.
#===============================================================================

import struct, sys
import time

from PyQt5.QtCore import QIODevice, QThread, pyqtSignal
from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo
from PyQt5.QtWidgets import QApplication

from avr_isp import intelHex, ispBase


class Stk500v2(ispBase.IspBase, QSerialPort):
		progressCallback = pyqtSignal(int, int)

		def __init__(self):
			super(Stk500v2, self).__init__()
			self.seq = 1
			self.lastAddr = -1
			self.portInfo = None

		def connect(self, port = 'COM4', speed = 115200):
			self.portInfo = QSerialPortInfo(port)
			self.setPort(self.portInfo)
			self.setBaudRate(speed)

			if self.portInfo.isNull():
				raise portError(portError.errorInvalid, port)
			else:
				if self.portInfo.isBusy():
					raise portError(portError.errorBusy, port)
				else:
					if self.open(QIODevice.ReadWrite):
# 						self.setBreakEnabled()
						self.entryISP()
					else:
						raise portError(portError.errorOpen, port)

		def close(self):
			super(Stk500v2, self).close()
			self.portInfo = None

		def entryISP(self):
			self.seq = 1
			# Reset the controller
			self.setDataTerminalReady(True)
			QThread.msleep(100)
			self.setDataTerminalReady(False)
			QThread.msleep(200)
			self.clear()

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
				self.sendMessage([0x13, pageSize >> 8, pageSize & 0xFF, 0xc1, 0x0a, 0x40, 0x4c, 0x20, 0x00, 0x00] + flashData[(i * pageSize):(i * pageSize + pageSize)])
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
				self.write(message)
				self.flush()
			except:
				raise ispBase.IspError("Serial send timeout")
			self.seq = (self.seq + 1) & 0xFF
			
			if(self.waitForReadyRead(100)):
				return self.recvMessage()
			else:
				raise ispBase.IspError("Serial recv timeout")

		def recvMessage(self):
			state = 'Start'
			checksum = 0
			while True:
				s = self.read(1)
				if(len(s) < 1):
					if(self.waitForReadyRead(20)):
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


class portError(Exception):
	errorInvalid = 0
	errorBusy = 1
	errorOpen = 2

	def __init__(self, value, port):
		self.value = value
		self.port = str(port)

	def __str__(self):
		if self.value == self.errorInvalid:
			return "Invalid serial port : " + self.port + " !"
		elif self.value == self.errorBusy:
			return "Serial port " + self.port + " is busy!"
		elif self.value == self.errorOpen:
			return "Serial port " + self.port + " failed to open!"


class stk500v2Thread(QThread):
	stateCallback = pyqtSignal([str], [Exception])

	def __init__(self, parent, port, speed, filename, callback = None):
		super(stk500v2Thread, self).__init__()
		self.parent = parent
		self.port = port
		self.speed = speed
		self.filename = filename
		self.callback = callback
		self.programmer = None
		self.isWork = False
		self.finished.connect(self.done)

	def run(self):
		self.isWork = True
		try:
			self.programmer = Stk500v2()
			if self.callback is not None:
				self.programmer.progressCallback.connect(self.callback)

			if self.parent is None:
				runProgrammer(self.port, self.speed, self.filename, self.programmer)
			else:
				self.stateCallback[str].emit(self.tr("Connecting..."))
				self.msleep(200)
				self.programmer.connect(self.port, self.speed)

				self.stateCallback[str].emit(self.tr("Programming..."))
				self.programmer.programChip(intelHex.readHex(self.filename))
		except Exception as e:
			if(self.isInterruptionRequested()):
				print("Int")
			else:
				if self.parent is not None:
					self.stateCallback[Exception].emit(e)
					while(self.isWork):
						pass  # 等待父进程处理异常
				else:
					raise e
			self.isWork = False
		finally:
			if self.programmer.isConnected():
				self.programmer.fastReset()
				self.programmer.close()
			self.programmer = None

	def isReady(self):
		return self.programmer is not None and self.programmer.isConnected()

	def done(self):
		if self.parent is not None:
			if(self.isWork):
				self.isWork = False
				self.stateCallback[str].emit(self.tr("Done!"))
			else:
				print("Success!")
		else:
			print("Failure!")

	def terminate(self):
		if self.programmer is not None:
			self.requestInterruption()
			self.programmer.close()
			self.programmer = None
			return super(stk500v2Thread, self).terminate()


def runProgrammer(port, speed, filename, programmer = None):
		""" Run an STK500v2 program on serial port 'port' and write 'filename' into flash. """
		if programmer is None:
			programmer = Stk500v2()
		programmer.connect(port = port, speed = speed)
		programmer.programChip(intelHex.readHex(filename))
		programmer.close()


def main():
		""" Entry point to call the stk500v2 programmer from the commandline. """
		programmer = Stk500v2()
		try:
			if(len(sys.argv) > 2):
				programmer.connect(sys.argv[1])
				programmer.programChip(intelHex.readHex(sys.argv[2]))
			else:
				programmer.connect("COM4")
				programmer.programChip(intelHex.readHex("D:/OneDrive/Desktop/CreatBot F160 01 EN KTC ( AUTO_LEVELING ).hex"))
		except portError as e:
			print(e.value)
			print("PortError: " + str(e))
		except ispBase.IspError as e:
			print("IspError: " + str(e))
		except intelHex.formatError as e:
			print("HexError: " + str(e))
		finally:
			programmer.close()


if __name__ == '__main__':
# 	main()
# 	runProgrammer("COM4", 115200, "D:/OneDrive/Desktop/CreatBot F160 01 EN KTC ( AUTO_LEVELING ).hex")

	app = QApplication(sys.argv)
	task = stk500v2Thread(None, "COM4", 115200, "D:/OneDrive/Desktop/CreatBot F160 01 EN KTC ( AUTO_LEVELING ).hex")
# 	task = stk500v2Thread(None, "COM4", 115200, "D:/OneDrive/Desktop/test.hex")
	try:
		task.start()
	except Exception as e:
		print(e)

	sys.exit(app.exec())

