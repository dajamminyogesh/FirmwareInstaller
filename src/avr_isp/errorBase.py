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
