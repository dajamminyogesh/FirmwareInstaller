'''
Created on 2017年8月15日

@author: CreatBot-SW
'''

import os
import sys
import time

from PyQt5 import QtSerialPort, QtCore, QtWidgets
from PyQt5.Qt import pyqtSignal
from PyQt5.QtCore import QSize, QDir, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtSerialPort import QSerialPortInfo
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QGroupBox, \
    QRadioButton, QGridLayout, QWidget, QProgressBar, QStatusBar, QComboBox, QLabel, \
    QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QCheckBox

from avr_isp.intelHex import formatError
from avr_isp.ispBase import IspError
from avr_isp.stk500v2 import stk500v2Thread, portError

# from DfuseTool import DfuseTool as DFUse
from pydfu import DFUTool as DFUse

if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
else:
    bundle_dir = os.path.dirname(os.path.abspath(__file__))


def portListAll():
    return [port.portName() for port in QSerialPortInfo.availablePorts()]


def portList():
    return [port.portName() for port in QSerialPortInfo.availablePorts() if port.description() == "Arduino Mega 2560"]


class countLabel(QLabel):

    def __init__(self, text):
        super(countLabel, self).__init__(text)

    def mouseDoubleClickEvent(self, e):
        self.setText("0")
        return super(countLabel, self).mouseDoubleClickEvent(e)


class portCombox(QComboBox):
    showPopupSignal = pyqtSignal(bool)

    def __init__(self):
        super(portCombox, self).__init__()

    def showPopup(self):
        self.showPopupSignal.emit(True)
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        return super(portCombox, self).showPopup()


class mainWindow(QWidget):

    def __init__(self):
        super(mainWindow, self).__init__()
        self.setWindowTitle(self.tr("Firmware Installer"))
        self.setWindowIcon(QIcon(os.path.join(bundle_dir, "ico.ico")))
        self.setFixedSize(QSize(480, 240))
        self.setAcceptDrops(True)

        self.portUpdateTimer = QTimer()
        self.portUpdateTimer.timeout.connect(self.portUpdate)
        self.portUpdateTimer.start(200)

        self.autoTimer = QTimer()
        # self.autoTimer.setSingleShot(True)
        self.autoTimer.timeout.connect(self.portUpdate)
        # self.autoTimer.start(1000)

        self.task = None

        self.initUI()
        self.configUI()
        self.resize()

    def initUI(self):
        mainLayout = QVBoxLayout()

        self.portBox = QGroupBox(self.tr("Port Selection"))
        self.fileBox = QGroupBox(self.tr("File Selection"))
        self.ctrlBox = QGroupBox(self.tr("Control"))

        # PortBox widget
        self.autoRadio = QRadioButton(self.tr("Auto"))
        self.manualRadio = QRadioButton(self.tr("Manual"))

        self.manualBox = QGroupBox()
        manualLayout = QHBoxLayout()
        self.manualBox.setLayout(manualLayout)

        self.portCombo = portCombox()  # 端口号下拉选框
        self.baudCombo = QComboBox()  # 波特率
        manualLayout.addWidget(QLabel(self.tr("Port:")))
        manualLayout.addWidget(self.portCombo)
        manualLayout.addStretch()
        manualLayout.addWidget(QLabel(self.tr("Baudrate:")))
        manualLayout.addWidget(self.baudCombo)
        manualLayout.addStretch()

        portLayout = QGridLayout()
        self.portBox.setLayout(portLayout)
        portLayout.addWidget(self.autoRadio, 0, 0)
        portLayout.addWidget(self.manualRadio, 0, 1)
        portLayout.addWidget(self.manualBox, 1, 0, 1, 2)

        # FileBox widget
        self.file = QLineEdit()
        self.file.setPlaceholderText("Please select a firmware file.")
        self.file.setReadOnly(True)
        self.file.setFrame(False)
        self.file.setDragEnabled(True)
        # 		self.file.setDisabled(True)
        self.fileBtn = QPushButton(self.tr("&Open"))

        fileLayout = QHBoxLayout()
        self.fileBox.setLayout(fileLayout)
        fileLayout.addWidget(QLabel(self.tr("firmware:")))
        fileLayout.addWidget(self.file)
        fileLayout.addWidget(self.fileBtn)

        # CtrlBox widget
        self.installBtn = QPushButton(self.tr("&Install"))
        self.stopBtn = QPushButton(self.tr("&Stop"))
        self.autoCheck = QCheckBox(self.tr("Auto Install"))
        self.autoTimeLabel = QLabel(self.tr("Idle Time:"))
        self.autoTimeLabel2 = QLabel(self.tr("s"))
        self.autoTime = QLineEdit("3")
        self.autoTime.setInputMask("00")
        self.autoTime.setMaximumWidth(20)

        layout1 = QVBoxLayout()
        layout1.addWidget(self.autoCheck)
        layout2 = QHBoxLayout()
        layout2.addWidget(self.autoTimeLabel)
        layout2.addWidget(self.autoTime)
        layout2.addWidget(self.autoTimeLabel2)
        layout1.addLayout(layout2)
        self.autoInstallWidget = QWidget()
        self.autoInstallWidget.setLayout(layout1)

        ctrlLayout = QHBoxLayout()
        self.ctrlBox.setLayout(ctrlLayout)

        ctrlLayout.addWidget(self.autoInstallWidget)
        ctrlLayout.addStretch()
        ctrlLayout.addWidget(self.installBtn)
        ctrlLayout.addStretch()
        ctrlLayout.addWidget(self.stopBtn)
        ctrlLayout.addStretch()

        # 进度条和状态栏
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.statusBar = QStatusBar()
        self.statusBar.setSizeGripEnabled(False)

        self.tryAgainLabel = QLabel(self.tr("Try again..."))
        self.tryAgain = QLabel("0")
        self.statusBar.addPermanentWidget(self.tryAgainLabel)
        self.statusBar.addPermanentWidget(self.tryAgain)

        # 计数栏
        self.countBar = QStatusBar()
        self.countBar.setSizeGripEnabled(False)
        self.countBar.setStyleSheet(
            "QStatusBar::item { border: 0 } QLabel {border:0; font-size: 14px; font-weight: bold}")
        countSuccessLabel = QLabel("Success: ")
        countFailureLabel = QLabel("Failure: ")
        self.countSuccess = countLabel("0")
        self.countFailure = countLabel("0")
        countSuccessLabel.setStyleSheet("QLabel {color: green}")
        self.countSuccess.setStyleSheet("QLabel {color: green}")
        countFailureLabel.setStyleSheet("QLabel {color: red}")
        self.countFailure.setStyleSheet("QLabel {color: red}")

        # print(self.countFailure.mouseDoubleClickEvent())
        self.url = QLabel("<a href = www.creatbot.com>www.CreatBot.com</a>")
        self.url.setOpenExternalLinks(True)

        self.countBar.addWidget(QLabel(""), 1)
        self.countBar.addWidget(countSuccessLabel)
        self.countBar.addWidget(self.countSuccess, 1)
        self.countBar.addWidget(countFailureLabel)
        self.countBar.addWidget(self.countFailure, 1)
        self.countBar.addWidget(self.url)
        self.countBar.addWidget(QLabel(""), 1)

        # MainLayout
        mainLayout.addWidget(self.portBox)
        mainLayout.addWidget(self.fileBox)
        mainLayout.addWidget(self.ctrlBox)
        mainLayout.addWidget(self.progress)
        mainLayout.addWidget(self.statusBar)
        mainLayout.addWidget(self.countBar)
        self.setLayout(mainLayout)

    def configUI(self):
        self.baudCombo.addItems([str(baud) for baud in QSerialPortInfo.standardBaudRates()])

        self.progress.hide()
        self.statusBar.hide()
        self.stopBtn.setDisabled(True)
        self.portCombo.show()

        self.autoRadio.toggled.connect(self.manualBox.setDisabled)
        self.autoRadio.toggled.connect(self.autoInstallWidget.setVisible)
        self.autoRadio.toggled.connect(self.resize)

        self.manualRadio.clicked.connect(self.disableAutoInstall)
        self.manualRadio.clicked.connect(self.resize)

        self.autoCheck.toggled.connect(self.autoTimeLabel.setEnabled)
        self.autoCheck.toggled.connect(self.autoTime.setEnabled)
        self.autoCheck.toggled.connect(self.autoTimeLabel2.setEnabled)
        self.autoCheck.stateChanged.connect(self.autoStateChangeAction)

        self.portCombo.showPopupSignal.connect(self.portUpdate)  # 弹出下拉选框，更新可用端口列表
        self.autoTime.returnPressed.connect(self.autoTimeChangeAction)
        self.statusBar.messageChanged.connect(self.stateClearAction)

        # 默认选中
        self.autoRadio.click()
        # self.manualRadio.click()
        # self.autoCheck.click()

        self.fileBtn.clicked.connect(self.selectFile)
        self.installBtn.clicked.connect(self.installFile)
        self.installBtn.setFocus()
        self.stopBtn.clicked.connect(self.stopInstall)

        self.file.__class__.dragEnterEvent = self.dragEnterEvent

    def portUpdate(self, forceUpdate=False):
        """ Auto 监听端口 """
        print("search port")
        if self.autoRadio.isChecked():

            self.baudCombo.setCurrentText("115200")
            # self.portCombo.addItems(portList())
            # self.portCombo.clear()
            port_list = QSerialPortInfo.availablePorts()
            for port in port_list:
                print(':--:', port.portName(), port.description())
                if port.description() not in ["Arduino Mega 2560", "USB-SERIAL CH340"]:  # 过滤2560和CH340
                    continue
                self.portCombo.addItem(port.portName() + " (" + port.description() + ")", port.portName())

            if len(port_list) > 0:
                port = port_list[0]
                info = QSerialPortInfo(port)
                print(info.productIdentifier())
                if info.productIdentifier() == 0:
                    return
                if not self.installBtn.isEnabled():
                    self.installFile()

        else:
            currentPortData = self.portCombo.currentData()
            if forceUpdate or (currentPortData and currentPortData not in [port.portName() for port in
                                                                           QSerialPortInfo.availablePorts()]):
                self.portCombo.clear()
                for port in QSerialPortInfo.availablePorts():
                    self.portCombo.addItem(port.portName() + " (" + port.description() + ")", port.portName())
                self.portCombo.setCurrentIndex(self.portCombo.findData(currentPortData))

        self.portCombo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.baudCombo.setSizeAdjustPolicy(QComboBox.AdjustToContents)

    def disableAutoInstall(self):
        self.autoCheck.setChecked(False)

    def autoStateChangeAction(self, check):
        if not check and self.autoTimer.remainingTime() > 0:
            self.stopInstall()

        if check:
            #  开启自动安装的端口扫描
            self.portUpdateTimer.stop()
            self.autoTimer.start(int(self.autoTime.text())*1000)
        else:
            self.autoTimer.stop()
            self.portUpdateTimer.start(200)

    def autoTimeChangeAction(self):
        """ 修改时间间隔 """
        self.autoTime.clearFocus()
        if self.autoCheck.isChecked() and self.autoTimer.remainingTime() > 0:
            self.autoTimer.stop()
            self.installFile()

    def stateClearAction(self, msg):
        """ 清理状态栏 """
        if msg == "" and self.statusBar.isVisible():
            self.statusBar.hide()
        if msg != "" and self.statusBar.isHidden():
            self.statusBar.show()
        self.resize()

    def selectFile(self):
        """ 选择固件文件 """
        hexFileDialog = QFileDialog()
        hexFileDialog.setWindowTitle(self.tr("Select firmware file"))
        # filesFilter = "firmware file (*.hex)|*.bin|" "All files (*.*)|*.*"
        filesFilter = "firmware file (*.hex | *.bin)"
        hexFileDialog.setNameFilter(self.tr(filesFilter))
        hexFileDialog.setFileMode(QFileDialog.ExistingFile)
        if (self.file.text() == ""):
            hexFileDialog.setDirectory(QDir.home())  # 设置为Home目录
        else:
            fileDir = QDir(self.file.text())
            fileDir.cdUp()
            if (fileDir.exists()):
                hexFileDialog.setDirectory(fileDir)  # 设置为当前文件所在目录
            else:
                hexFileDialog.setDirectory(QDir.home())
        if (hexFileDialog.exec()):
            self.file.setText(hexFileDialog.selectedFiles()[0])

    def installFile(self, notFromButton=True):
        """ 开始安装 """
        print("-------------------开始安装-------------------")
        # for port in QSerialPortInfo.availablePorts():
        #     print('port.description===', port.portName())
        #     print('port.description===', port.description())
        #     info = QSerialPortInfo(port)
        #     print(info.productIdentifier())
        #     print(info.vendorIdentifier())

        if self.file.text() == "":
            if not notFromButton:
                self.selectFile()
                self.installFile(True)
        else:
            if self.autoTimer.remainingTime() > 0:
                self.autoTimer.stop()

            port_list = QSerialPortInfo.availablePorts()
            if len(port_list) <= 0:
                QtWidgets.QMessageBox.about(self, "提示", "没有可用的串口!")
                return

            port = port_list[0]
            info = QSerialPortInfo(port)

            port_Name = None
            baud_rate = None
            if self.manualRadio.isChecked():
                if self.portCombo.currentData() is None:
                    QtWidgets.QMessageBox.about(self, "提示", "请选择串口设备")
                    return
                else:
                    port_Name = self.portCombo.currentData()
                    baud_rate = int(self.baudCombo.currentText())

            else:
                port_Name = info.portName()
                baud_rate = QtSerialPort.QSerialPort.Baud115200

            print("port:", port_Name)
            print("baudCombo:", baud_rate)
            print(info.portName())
            print(info.description())
            print(info.productIdentifier())
            print(info.vendorIdentifier())
            if info.productIdentifier() == 0:
                self.autoTimer.start(1000)
                pass

            if info.vendorIdentifier() == 1155:
                print("------命令开启DFU模式 start------")
                self.statusBar.showMessage("Serial to DFU...")
                serial = QtSerialPort.QSerialPort(self)
                serial.setPortName(port_Name)
                serial.setBaudRate(baud_rate)
                serial.setDataBits(QtSerialPort.QSerialPort.Data8)
                serial.setParity(QtSerialPort.QSerialPort.NoParity)
                serial.setStopBits(QtSerialPort.QSerialPort.OneStop)
                serial.setFlowControl(QtSerialPort.QSerialPort.NoFlowControl)

                if not serial.open(QtCore.QIODevice.ReadWrite):
                    # QtWidgets.QMessageBox.about(self, "提示", "无法打开串口!")
                    return

                data = bytes("M9999\r", encoding='utf-8')
                data = QtCore.QByteArray(data)
                serial.write(data)
                print("------命令开启DFU模式 end------")
                self.statusBar.showMessage("Serial to dfu...")

                self.task = DFUse(self, self.file.text(), self.progressUpdate)
                self.task.stateCallback[str].connect(self.stateUpdate)
                self.task.stateCallback[Exception].connect(self.stateUpdate)
                self.task.finished.connect(self.autoAction)  # 检查是否自动烧写，并启动。
                # self.task.start()

            elif info.vendorIdentifier() != 0:
                self.task = stk500v2Thread(self, self.portCombo.currentData(), int(self.baudCombo.currentText()),
                                           self.file.text(), self.progressUpdate)
                self.task.stateCallback[str].connect(self.stateUpdate)
                self.task.stateCallback[Exception].connect(self.stateUpdate)
                self.task.finished.connect(self.autoAction)
                self.task.start()

            # 开始烧录，刷新UI
            # self.statusBar.showMessage(" ")
            self.portBox.setDisabled(True)
            self.fileBox.setDisabled(True)
            self.installBtn.setDisabled(True)
            self.stopBtn.setEnabled(True)
            self.progress.show()
            self.resize()

    def stopInstall(self, succeed=False, autoInstall=False):
        """ 停止自动安装 """
        if autoInstall:
            self.progress.reset()
        else:
            self.portBox.setEnabled(True)
            self.fileBox.setEnabled(True)
            self.installBtn.setEnabled(True)
            self.stopBtn.setDisabled(True)
            self.progress.reset()
            self.progress.hide()
            self.tryAgain.setText("0")
            self.resize()

        if succeed:
            self.countSuccess.setText(str(int(self.countSuccess.text()) + 1))
            self.task = None
        else:
            # if self.autoTimer.remainingTime() != -1:
            #     self.autoTimer.stop()
            if self.task is not None and self.task.isRunning():
                self.task.finished.disconnect()
                if self.task.isReady():
                    self.countFailure.setText(str(int(self.countFailure.text()) + 1))

                if self.task.isInterruptionRequested():
                    pass
                else:
                    # self.task.requestInterruption()
                    self.task.terminate()
                    self.statusBar.clearMessage()
            # self.task = None
            else:
                self.statusBar.clearMessage()

    def autoAction(self):
        """ 上一个任务结束后，开启新的烧录任务 """
        self.task = None
        self.statusBar.showMessage("Done!")
        self.stopInstall(True, self.autoCheck.isChecked())

        #  开启自动安装
        if self.autoCheck.isChecked():
            if self.autoTimer.remainingTime() > 0:
                self.autoTimer.stop()
            self.autoTimer.start(int(self.autoTime.text()) * 1000)

    def resize(self):
        self.setFixedHeight(self.sizeHint().height())

    def progressUpdate(self, cur, total):
        """ 进度条 """
        self.progress.setMaximum(total)
        self.progress.setValue(cur)

    def stateUpdate(self, stateOrError):
        """ 安装状态 """
        self.tryAgainLabel.setHidden(True)
        self.tryAgain.setHidden(True)
        if self.task.isReady():
            self.tryAgain.setText("0")

        print(stateOrError, str)
        if type(stateOrError) == str:
            print("222---")
            # 		self.statusBar.setStyleSheet("QStatusBar::item { border: 0 } QLabel {color: red; font-weight: bold}")
            self.statusBar.setStyleSheet(
                "QStatusBar {font-weight: bold; color: black}  QStatusBar::item { border: 0 } QLabel {font-weight: bold}")
            if self.task is not None and not self.task.isWork and not self.autoCheck.isChecked():
                print("statusBar---")
                self.statusBar.showMessage(stateOrError, 3000)
            else:
                print("else---")
                self.statusBar.showMessage(stateOrError)

        else:
            print("333---")
            self.task.requestInterruption()
            self.statusBar.setStyleSheet(
                "QStatusBar {font-weight: bold; color: red} QStatusBar::item { border: 0 } QLabel {font-weight: bold; color: red}")

            if type(stateOrError) == portError:
                if (stateOrError.value in [portError.errorInvalid, portError.errorBusy]) and (
                        int(self.tryAgain.text()) < 20):
                    self.statusBar.showMessage("PortError: " + str(stateOrError))
                    self.tryAgain.setText(str(int(self.tryAgain.text()) + 1))
                    self.tryAgainLabel.setVisible(True)
                    self.tryAgain.setVisible(True)
                    self.stopInstall(autoInstall=True)
                    self.autoTimer.start(1000)  # 1秒自动重试
                else:
                    self.statusBar.showMessage("PortError: " + str(stateOrError), 5000)
                    self.stopInstall()
            elif type(stateOrError) == IspError:
                if self.autoCheck.isChecked():
                    self.statusBar.showMessage("IspError: " + str(stateOrError))
                    self.tryAgainLabel.setVisible(True)
                    self.tryAgain.setVisible(True)
                    self.stopInstall(autoInstall=True)
                    self.autoTimer.start(int(self.autoTime.text()) * 1000)
                else:
                    self.statusBar.showMessage("IspError: " + str(stateOrError), 5000)
                    self.stopInstall()
            elif type(stateOrError) == formatError:
                self.statusBar.showMessage("HexError: " + str(stateOrError), 5000)
                self.stopInstall()
            else:
                self.statusBar.showMessage("Error: " + str(stateOrError), 5000)
                self.stopInstall()
            print("1111---")

            self.task.isWork = False
            self.task.wait(100)
            self.task = None


if __name__ == '__main__':

    app = QApplication(sys.argv)

    win = mainWindow()
    win.show()

    if len(sys.argv) > 1:  # 关联hex文件自动安装
        win.portUpdate()
        win.file.setText(sys.argv[1])
        win.installBtn.click()

    sys.exit(app.exec())
